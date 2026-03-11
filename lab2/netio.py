import select
import socket
import time
import zlib
import struct
from builtins import bytes
from enum import Enum
from typing import Tuple
import netbytes

MASK32 = 0xFFFFFFFF
long_size = 8

OK = "OK"
CONNECTION_CLOSED = "Соединение с сервером потеряно"

class Protocol(Enum):
    TCP = 'tcp'
    UDP = 'udp'

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

    def r_line(self):
        raise NotImplementedError

    def r_long(self):
        return int.from_bytes(self.r_exact(long_size), 'big')

    def r_exact(self, num_bytes):
        raise NotImplementedError

    def send_command(self, data):
        self.w_line(data)

    def w_line(self, data):
        data = (str(data) + '\n').encode()
        self.w_data(data)

    def w_long(self, long):
        self.w_data(long.to_bytes(long_size, 'big'))

    def w_data(self, data):
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

class TcpConnection(NetConnection):
    def __init__(self, sock):
        super().__init__(sock, sock.getpeername())

    def r_line(self):
        buffer = b""
        while True:
            try:
                data = self.sock.recv(netbytes.Size.KILOBYTE)
                if not data:
                    return None
                buffer += data
                if b'\n' in buffer:
                    line, _, _ = buffer.partition(b'\n')
                    return line.decode().strip()
            except UnicodeDecodeError:
                return None

    def r_exact(self, num_bytes):
        buffer = b""
        try:
            while len(buffer) < num_bytes:
                chunk = self.sock.recv(num_bytes - len(buffer))
                if not chunk:
                    return None
                buffer += chunk
            return buffer if len(buffer) == num_bytes else None
        except UnicodeDecodeError:
            return None

    def w_data(self, data):
        self.sock.sendall(data)


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
    ACK_DELAY_MASK = (1 << ACK_DELAY) - 1
    ACK_DELAY_BYTE_COUNT = (ACK_DELAY + 7) // 8
    ACK_SIZE = SESS_SIZE + SEQ_SIZE + ACK_DELAY_BYTE_COUNT + CRC_SIZE

    def __init__(self, sock, addr, timeout = NetConnection.DEFAULT_TIMEOUT):
        super().__init__(sock, addr)
        self.timeout = timeout
        self._transmit_id = 0
        self._last_receive_id = -1
        self._first_send = True
        self._last_ack = None
        self._last_ack_expected_seq = 0
        self._last_ack_time = 0.0
        self._hdr_struct = struct.Struct('!III')
        self._ack_struct = struct.Struct(f'!II{self.ACK_DELAY_BYTE_COUNT}sI')
        self._crc32 = zlib.crc32
        self._time = time.monotonic
        self._win_pkts = [b''] * self.WINDOW_SIZE
        self._win_seqs = [-1] * self.WINDOW_SIZE

    def r_line(self):
        data = self._receive_udp_until(lambda buf: b'\n' in buf)
        return data.partition(b'\n')[0].decode().strip()

    def r_exact(self, num_bytes):
        return self._receive_udp_until(lambda buf: len(buf) >= num_bytes)[:num_bytes]

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
        while self._last_ack:
            try:
                if max_time <= now():
                    raise socket.timeout
                _, addr = self.sock.recvfrom(self.TOTAL_SIZE)
                if addr != self.addr:
                    continue
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
                    sack = self._get_sack()
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

    def send_command(self, data):
        self._last_receive_id = -1
        self._transmit_id = 0
        self.w_line(data)

    def _receive_udp_until(self, condition_func):
        self.sock.settimeout(self.READ_TIMEOUT)
        assembled = bytearray()
        expected_seq = 0
        window_mask = 0
        delayed_acks = 0
        start_time = self._time()
        new_sess = False
        while True:
            if start_time + self.timeout <= self._time():
                raise socket.timeout
            try:
                packet, addr = self.sock.recvfrom(self.TOTAL_SIZE)
            except socket.timeout:
                continue

            if addr != self.addr:
                if self.addr is None:
                    self.addr = addr
                continue

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
                return bytes(assembled)

            if delayed_acks >= self.ACK_DELAY and expected_seq:
                self._send_sack(expected_seq - 1, window_mask)
                delayed_acks = 0

    def _get_sack(self):
        try:
            packet, addr = self.sock.recvfrom(self.ACK_SIZE)
        except socket.timeout:
            raise
        except Exception:
            return
        if addr != self.addr:
            return

        if len(packet) != self.ACK_SIZE:
            return

        sess_id, seq, mask_bytes, crc_received = self._ack_struct.unpack_from(packet)

        if sess_id != self._transmit_id:
            return

        start = self.SESS_SIZE
        length = start + self.SEQ_SIZE + self.ACK_DELAY_BYTE_COUNT

        if not self._is_valid_crc(packet[start:length], crc_received):
            return

        mask = int.from_bytes(mask_bytes, 'big')
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
        mask_bytes = mask.to_bytes(self.ACK_DELAY_BYTE_COUNT, 'big')
        crc_input = bytearray()
        crc_input.extend(max_seq.to_bytes(self.SEQ_SIZE, 'big'))
        crc_input.extend(mask_bytes)
        crc = self._calculate_crc(crc_input)

        return self._ack_struct.pack(
            session_id,
            max_seq,
            mask_bytes,
            crc
        )

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
