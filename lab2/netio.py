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
        data = self.r_exact(long_size)
        if not data:
            return None
        return int.from_bytes(data, 'big')

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
        self._read_buffer = b""

    def r_line(self):
        while True:
            try:
                if b'\n' in self._read_buffer:
                    line, _, rest = self._read_buffer.partition(b'\n')
                    self._read_buffer = rest
                    return line.decode(errors="ignore").strip()
                data = self.sock.recv(netbytes.Size.KILOBYTE)
                if not data:
                    self._read_buffer = b""
                    return None
                self._read_buffer += data
            except UnicodeDecodeError:
                self._read_buffer = b""
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
    # RTO (время ожидания SACK) увеличено с запасом на накопление delayed-ACK
    ACK_TIMEOUT = 0.3
    ACK_RESEND_INTERVAL = 0.05
    READ_TIMEOUT = 0.5
    CRC_SIZE = 4
    SEQ_SIZE = 4
    SESS_SIZE = 4
    WINDOW_SIZE = 256
    # PAYLOAD_SIZE подобран под Ethernet MTU 1500:
    # 1500 - 20 (IP) - 8 (UDP) = 1472 байт UDP-payload, минус 12 байт нашего заголовка = 1460
    PAYLOAD_SIZE = 1460
    WINDOW_FULL_MASK = (1 << WINDOW_SIZE) - 1
    HEADER_SIZE = SESS_SIZE + CRC_SIZE + SEQ_SIZE
    TOTAL_SIZE = HEADER_SIZE + PAYLOAD_SIZE
    # Ширина SACK-маски равна размеру окна: один SACK покрывает всё окно (256 бит = 32 байта)
    SACK_MASK_BITS = WINDOW_SIZE
    SACK_MASK_BYTES = (SACK_MASK_BITS + 7) // 8
    SACK_FULL_MASK = (1 << SACK_MASK_BITS) - 1
    # Порог накопления delayed-ACK (как часто приёмник шлёт SACK), не связан с шириной маски
    ACK_DELAY = WINDOW_SIZE // 4
    ACK_SIZE = SESS_SIZE + SEQ_SIZE + SACK_MASK_BYTES + CRC_SIZE
    SOCK_BUFFER_SIZE = 4 * 1024 * 1024

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
        self._ack_struct = struct.Struct(f'!II{self.SACK_MASK_BYTES}sI')
        self._crc32 = zlib.crc32
        self._time = time.monotonic
        # Отдельные буферы для отправки и приёма (раньше делили один и тот же — баг индексации)
        self._win_pkts = [b''] * self.WINDOW_SIZE
        self._win_seqs = [-1] * self.WINDOW_SIZE
        self._recv_pkts = [b''] * self.WINDOW_SIZE
        self._tune_socket_buffers()

    def _tune_socket_buffers(self):
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.SOCK_BUFFER_SIZE)
        except (OSError, socket.error):
            pass
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.SOCK_BUFFER_SIZE)
        except (OSError, socket.error):
            pass

    def r_line(self):
        data = self._receive_udp_until(lambda buf: b'\n' in buf)
        return data.partition(b'\n')[0].decode().strip()

    def r_exact(self, num_bytes):
        return self._receive_udp_until(lambda buf: len(buf) >= num_bytes)[:num_bytes]

    def w_data(self, data: bytes):
        mv = memoryview(data)
        total_len = len(mv)
        payload_size = self.PAYLOAD_SIZE
        window_size = self.WINDOW_SIZE
        # Число датаграмм для этого блока; нумерация seq начинается с 0
        seq_count = (total_len + payload_size - 1) // payload_size if total_len > 0 else 0

        self._transmit_id = (self._transmit_id + 1) & MASK32
        self.sock.settimeout(self.ACK_TIMEOUT)

        # Сброс возможного остаточного состояния приёмной роли
        now = self._time
        max_time = now() + self.timeout
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

        if seq_count == 0:
            return

        pkts = self._win_pkts
        acked = bytearray(seq_count)  # 1 == пакет точно получен приёмником (по SACK-маске)
        base = 0           # самый старый ещё не подтверждённый seq (нижняя граница окна)
        next_seq = 0       # следующий seq для первичной отправки

        deadline = now() + self.timeout

        while base < seq_count:
            if deadline <= now():
                raise socket.timeout

            # Заполняем окно новыми пакетами в пределах [base, base + WINDOW_SIZE)
            window_top = base + window_size
            while next_seq < seq_count and next_seq < window_top:
                off = next_seq * payload_size
                end = off + payload_size
                if end > total_len:
                    end = total_len
                payload = mv[off:end]
                crc = self._calculate_crc(payload)
                packet = self._build_packet(crc, next_seq, payload)
                pkts[next_seq % window_size] = packet
                self._send(packet)
                next_seq += 1

            # Собираем все доступные SACK в пределах RTO
            progressed = False
            while True:
                try:
                    sack = self._get_sack()
                except socket.timeout:
                    break
                if sack is None:
                    continue

                max_seq, mask = sack
                new_base = max_seq + 1
                if new_base > base:
                    base = new_base
                    progressed = True

                # Отмечаем выборочно подтверждённые (out-of-order) пакеты выше base
                d = 0
                m = mask
                while m:
                    if m & 1:
                        s = max_seq + 1 + d
                        if 0 <= s < seq_count:
                            acked[s] = 1
                    m >>= 1
                    d += 1

                if base >= seq_count:
                    break

            if base >= seq_count:
                break

            if not progressed:
                # RTO без продвижения окна: ретрансмитим самый старый реально неподтверждённый пакет
                s = base
                while s < next_seq and acked[s]:
                    s += 1
                if s < next_seq:
                    self._send(pkts[s % window_size])

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
        window_size = self.WINDOW_SIZE
        recv_pkts = self._recv_pkts
        while True:
            if start_time + self.timeout <= self._time():
                raise socket.timeout
            try:
                packet, addr = self.sock.recvfrom(self.TOTAL_SIZE)
            except socket.timeout:
                continue

            if self.addr is None:
                self.addr = addr
            elif addr != self.addr:
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
                # In-order пакет: добавляем и сливаем все подряд идущие буферизованные
                assembled.extend(payload)
                delayed_acks += 1
                expected_seq += 1
                window_mask >>= 1
                while window_mask & 1:
                    idx = expected_seq % window_size
                    assembled.extend(recv_pkts[idx])
                    window_mask >>= 1
                    expected_seq += 1
                    delayed_acks += 1
            elif delta < window_size:
                # Out-of-order: единая индексация seq % WINDOW_SIZE (совпадает с чтением)
                idx = seq % window_size
                bit = 1 << delta
                if not (window_mask & bit):
                    recv_pkts[idx] = bytes(payload)
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
        length = start + self.SEQ_SIZE + self.SACK_MASK_BYTES

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
        mask &= self.SACK_FULL_MASK
        mask_bytes = mask.to_bytes(self.SACK_MASK_BYTES, 'big')
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

    def _build_packet(self, crc: int, seq: int, payload) -> bytearray:
        # Предаллоцированный bytearray + pack_into: payload копируется один раз, без лишнего tobytes()
        buf = bytearray(self.HEADER_SIZE + len(payload))
        self._hdr_struct.pack_into(buf, 0, self._transmit_id, crc, seq)
        buf[self.HEADER_SIZE:] = payload
        return buf

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
