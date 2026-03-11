import socket
import struct
import threading
import time
import zlib
from builtins import bytes
from typing import Tuple

import netbytes

MASK32 = 0xFFFFFFFF
long_size = 8

OK = "OK"
CONNECTION_CLOSED = "Соединение с сервером потеряно"

_socket_locks = {}
_socket_locks_guard = threading.Lock()


def _get_socket_lock(sock):
    key = sock.fileno()
    with _socket_locks_guard:
        lock = _socket_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _socket_locks[key] = lock
        return lock


def peek_next_sender(sock, max_size=2048):
    if not hasattr(socket, "MSG_PEEK"):
        return None
    lock = _get_socket_lock(sock)
    with lock:
        try:
            _, addr = sock.recvfrom(max_size, socket.MSG_PEEK)
            return addr
        except (BlockingIOError, socket.timeout):
            return None


class Commands:
    ECHO = "ECHO"
    TIME = "TIME"
    CLOSE = "CLOSE"
    UPLOAD = "UPLOAD"
    DOWNLOAD = "DOWNLOAD"


class NetConnection:
    DEFAULT_TIMEOUT = 30

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.has_session = False
        self.timeout_time = 0
        self.timeout = self.DEFAULT_TIMEOUT
        self.message_timeout = 0.5

    def r_line(self):
        raise NotImplementedError

    def r_long(self):
        data = self.r_exact(long_size)
        if not data:
            return None
        return int.from_bytes(data, "big")

    def r_exact(self, num_bytes):
        raise NotImplementedError

    def send_command(self, data):
        self.w_line(data)

    def w_line(self, data):
        data = (str(data) + "\n").encode()
        self.w_data(data)

    def w_long(self, value):
        self.w_data(value.to_bytes(long_size, "big"))

    def w_data(self, data):
        raise NotImplementedError

    def try_w_data(self, data) -> int:
        raise NotImplementedError

    def try_r_exact(self, num_bytes):
        raise NotImplementedError

    def get_addr(self):
        return self.addr

    def get_status(self):
        result = self.r_line()
        if not result:
            return CONNECTION_CLOSED
        return result

    def send_status(self, status):
        self.w_line(status)

    def reset_timeout(self, is_message=False):
        value = self.message_timeout if is_message else self.timeout
        self.timeout_time = time.time() + value

    def is_time_over(self):
        return self.timeout_time <= time.time()


class TcpConnection(NetConnection):
    def __init__(self, sock):
        super().__init__(sock, sock.getpeername())
        self._read_buffer = b""

    def r_line(self):
        self.reset_timeout(is_message=True)
        while True:
            if b"\n" in self._read_buffer:
                line, _, rest = self._read_buffer.partition(b"\n")
                self._read_buffer = rest
                return line.decode(errors="ignore").strip()
            try:
                data = self.sock.recv(netbytes.Size.KILOBYTE)
                if not data:
                    self._read_buffer = b""
                    return None
                self._read_buffer += data
                self.reset_timeout(is_message=True)
            except (BlockingIOError, socket.timeout):
                if self.is_time_over():
                    raise socket.timeout
            except UnicodeDecodeError:
                self._read_buffer = b""
                return None

    def r_exact(self, num_bytes):
        self.reset_timeout(is_message=True)
        buffer = b""
        while len(buffer) < num_bytes:
            try:
                chunk = self.sock.recv(num_bytes - len(buffer))
                if not chunk:
                    return None
                buffer += chunk
                self.reset_timeout(is_message=True)
            except (BlockingIOError, socket.timeout):
                if self.is_time_over():
                    raise socket.timeout
            except UnicodeDecodeError:
                return None
        return buffer

    def w_data(self, data):
        total_sent = 0
        self.reset_timeout(is_message=True)
        while total_sent < len(data):
            try:
                sent = self.sock.send(data[total_sent:])
                if sent == 0:
                    raise RuntimeError("Соединение разорвано")
                total_sent += sent
                self.reset_timeout(is_message=True)
            except (BlockingIOError, socket.timeout):
                if self.is_time_over():
                    raise socket.timeout

    def try_r_exact(self, num_bytes):
        try:
            data = self.sock.recv(num_bytes)
        except (UnicodeDecodeError, BlockingIOError, socket.timeout):
            if self.is_time_over():
                raise socket.timeout
            return None
        if len(data) == 0:
            if self.is_time_over():
                raise socket.timeout
            return None
        self.reset_timeout()
        return data

    def try_w_data(self, data) -> int:
        try:
            n = self.sock.send(data)
        except (BlockingIOError, socket.timeout):
            if self.is_time_over():
                raise socket.timeout
            return 0
        if not n:
            if self.is_time_over():
                raise socket.timeout
        else:
            self.reset_timeout()
        return n

class UdpConnection(NetConnection):
    ACK_TIMEOUT = 0.1
    ACK_RESEND_INTERVAL = 0.05
    READ_TIMEOUT = 0.5
    CRC_SIZE = 4
    SEQ_SIZE = 4
    SESS_SIZE = 4
    WINDOW_SIZE = 256
    PAYLOAD_SIZE = 900
    WINDOW_FULL_MASK = (1 << WINDOW_SIZE) - 1
    HEADER_SIZE = SESS_SIZE + CRC_SIZE + SEQ_SIZE
    TOTAL_SIZE = HEADER_SIZE + PAYLOAD_SIZE
    ACK_DELAY = WINDOW_SIZE // 4
    ACK_DELAY_BYTE_COUNT = (ACK_DELAY + 7) // 8
    ACK_SIZE = SESS_SIZE + SEQ_SIZE + ACK_DELAY_BYTE_COUNT + CRC_SIZE

    def __init__(self, sock, addr, timeout=NetConnection.DEFAULT_TIMEOUT):
        super().__init__(sock, addr)
        self.timeout = timeout
        self._transmit_id = 0
        self._last_receive_id = -1
        self._last_ack = None
        self._last_ack_expected_seq = 0
        self._last_ack_time = 0.0
        self._hdr_struct = struct.Struct("!III")
        self._ack_struct = struct.Struct(f"!II{self.ACK_DELAY_BYTE_COUNT}sI")
        self._crc32 = zlib.crc32
        self._time = time.monotonic
        self._win_pkts = [b""] * self.WINDOW_SIZE
        self._win_seqs = [-1] * self.WINDOW_SIZE
        self._socket_lock = _get_socket_lock(sock)
        self._peek_flag = getattr(socket, "MSG_PEEK", 0)

    def _recv_from_self(self, max_size, deadline):
        while True:
            if deadline <= self._time():
                raise socket.timeout
            try:
                with self._socket_lock:
                    if self._peek_flag:
                        packet, addr = self.sock.recvfrom(max_size, self._peek_flag)
                        if self.addr is None:
                            packet, addr = self.sock.recvfrom(max_size)
                            self.addr = addr
                            self.reset_timeout()
                            return packet
                        if addr != self.addr:
                            pass
                        else:
                            packet, _ = self.sock.recvfrom(max_size)
                            self.reset_timeout()
                            return packet
                    else:
                        packet, addr = self.sock.recvfrom(max_size)
                        if self.addr is None:
                            self.addr = addr
                            self.reset_timeout()
                            return packet
                        if addr == self.addr:
                            self.reset_timeout()
                            return packet
                time.sleep(0.001)
            except (BlockingIOError, socket.timeout):
                time.sleep(0.001)

    def r_line(self):
        data = self._receive_udp_until(lambda buf: b"\n" in buf)
        return data.partition(b"\n")[0].decode(errors="ignore").strip()

    def r_exact(self, num_bytes):
        data = self._receive_udp_until(lambda buf: len(buf) >= num_bytes)
        return data[:num_bytes]

    def w_data(self, data: bytes):
        mv = memoryview(data)
        total_len = len(mv)
        offset = 0
        seq = 0
        now = self._time
        max_time = self._time() + self.timeout
        window_mask = 0
        window_full_mask = self.WINDOW_FULL_MASK
        self._transmit_id = (self._transmit_id + 1) & MASK32
        self.sock.settimeout(self.ACK_TIMEOUT)
        self.reset_timeout()

        while self._last_ack:
            try:
                if max_time <= now():
                    raise socket.timeout
                self._recv_from_self(self.TOTAL_SIZE, self._time() + self.ACK_TIMEOUT)
                self._resend_last_sack()
            except socket.timeout:
                self._last_ack = None

        while offset < total_len or window_mask != 0:
            if max_time <= now():
                raise socket.timeout

            while offset < total_len:
                temp_mask = ~window_mask & window_full_mask
                if temp_mask == 0:
                    break
                idx = (temp_mask & -temp_mask).bit_length() - 1
                remaining = total_len - offset
                payload_len = remaining if remaining < self.PAYLOAD_SIZE else self.PAYLOAD_SIZE
                payload = mv[offset:offset + payload_len]
                crc = self._calculate_crc(payload)
                packet = self._build_packet(crc, seq, payload)
                self._send(packet)
                self._win_seqs[idx] = seq
                self._win_pkts[idx] = packet
                window_mask |= (1 << idx)
                offset += payload_len
                seq += 1

            while True:
                try:
                    sack = self._get_sack(self._time() + self.ACK_TIMEOUT)
                except socket.timeout:
                    break

                if sack is None:
                    continue

                max_seq, mask = sack
                temp_mask = window_mask
                while temp_mask:
                    i = (temp_mask & -temp_mask).bit_length() - 1
                    temp_seq = self._win_seqs[i]
                    delta = temp_seq - (max_seq + 1)

                    if temp_seq <= max_seq or (0 <= delta < self.ACK_DELAY and ((mask >> delta) & 1)):
                        window_mask &= ~(1 << i)
                    temp_mask &= temp_mask - 1

                if window_mask == 0:
                    break

            temp_mask = window_mask
            while temp_mask:
                i = (temp_mask & -temp_mask).bit_length() - 1
                self._send(self._win_pkts[i])
                temp_mask &= temp_mask - 1

        self.reset_timeout()

    def send_command(self, data):
        self.w_line(data)

    def try_r_exact(self, num_bytes):
        old_timeout = self.timeout
        self.timeout = self.message_timeout
        try:
            return self.r_exact(num_bytes)
        except socket.timeout:
            if self.is_time_over():
                raise
            return None
        finally:
            self.timeout = old_timeout

    def try_w_data(self, data) -> int:
        old_timeout = self.timeout
        self.timeout = self.message_timeout
        try:
            self.w_data(data)
            return len(data)
        except socket.timeout:
            if self.is_time_over():
                raise
            return 0
        finally:
            self.timeout = old_timeout

    def _receive_udp_until(self, condition_func):
        self.sock.settimeout(self.READ_TIMEOUT)
        assembled = bytearray()
        expected_seq = 0
        window_mask = 0
        delayed_acks = 0
        start_time = self._time()
        new_sess = False

        while True:
            deadline = start_time + self.timeout
            packet = self._recv_from_self(self.TOTAL_SIZE, deadline)

            try:
                sess, crc, seq, payload = self._parse_packet(packet)
            except (UnicodeDecodeError, ValueError):
                continue

            if expected_seq == 0 and not new_sess:
                if sess != self._last_receive_id:
                    new_sess = True
                    self._last_ack = None
                    self._last_receive_id = sess
                else:
                    self._resend_last_sack()
                    continue
            elif sess != self._last_receive_id:
                continue

            if not self._is_valid_crc(payload, crc):
                continue

            if seq < expected_seq:
                if self._last_ack and self._last_ack_expected_seq == expected_seq:
                    self._resend_last_sack()
                else:
                    self._send_sack(expected_seq - 1, window_mask)
                continue

            delta = seq - expected_seq
            if delta == 0:
                assembled.extend(payload)
                delayed_acks += 1
                window_mask >>= 1
                while window_mask & 1:
                    idx = expected_seq % self.WINDOW_SIZE
                    assembled.extend(self._win_pkts[idx])
                    window_mask >>= 1
                    expected_seq += 1
                    delayed_acks += 1
                expected_seq += 1
            elif delta < self.WINDOW_SIZE:
                idx = (seq - 1) % self.WINDOW_SIZE
                bit = 1 << delta
                if not (window_mask & bit):
                    self._win_pkts[idx] = payload
                    window_mask |= bit
                    delayed_acks += 1

            if condition_func(assembled):
                self._send_final_sack(expected_seq - 1)
                self.reset_timeout()
                return bytes(assembled)

            if delayed_acks >= self.ACK_DELAY and expected_seq:
                self._send_sack(expected_seq - 1, window_mask)
                delayed_acks = 0

    def _get_sack(self, deadline):
        packet = self._recv_from_self(self.TOTAL_SIZE, deadline)
        if len(packet) != self.ACK_SIZE:
            return None

        sess_id, seq, mask_bytes, crc_received = self._ack_struct.unpack_from(packet)
        if sess_id != self._transmit_id:
            return None

        start = self.SESS_SIZE
        length = start + self.SEQ_SIZE + self.ACK_DELAY_BYTE_COUNT
        if not self._is_valid_crc(packet[start:length], crc_received):
            return None

        mask = int.from_bytes(mask_bytes, "big")
        return seq, mask

    def _send_sack(self, max_seq, mask):
        pkt = self._build_sack(self._last_receive_id, max_seq, mask)
        self._last_ack = pkt
        self._last_ack_expected_seq = max_seq + 1
        self._last_ack_time = self._time()
        self._send(pkt)

    def _send(self, data: bytes):
        try:
            self.sock.sendto(data, self.addr)
        except socket.timeout:
            return

    def _send_final_sack(self, final_seq: int):
        self._send_sack(final_seq, 0)

    def _resend_last_sack(self):
        now = self._time()
        if self._last_ack and now - self._last_ack_time > self.ACK_RESEND_INTERVAL:
            self._send(self._last_ack)
            self._last_ack_time = now

    def _build_sack(self, session_id, max_seq, mask):
        mask &= (1 << self.ACK_DELAY) - 1
        mask_bytes = mask.to_bytes(self.ACK_DELAY_BYTE_COUNT, "big")
        crc_input = bytearray()
        crc_input.extend(max_seq.to_bytes(self.SEQ_SIZE, "big"))
        crc_input.extend(mask_bytes)
        crc = self._calculate_crc(crc_input)
        return self._ack_struct.pack(session_id, max_seq, mask_bytes, crc)

    def _build_packet(self, crc: int, seq: int, payload: memoryview | bytes) -> bytes:
        hdr = self._hdr_struct.pack(self._transmit_id, crc, seq)
        return hdr + payload.tobytes()

    def _parse_packet(self, packet: bytes) -> Tuple[int, int, int, bytes]:
        if len(packet) < self.HEADER_SIZE:
            raise ValueError("Truncated UDP packet")
        sess, crc, seq = self._hdr_struct.unpack_from(packet)
        payload = packet[self.HEADER_SIZE:]
        return sess, crc, seq, payload

    def _is_valid_crc(self, data, crc: int):
        return self._calculate_crc(data) == crc

    def _calculate_crc(self, data):
        return self._crc32(data) & MASK32
