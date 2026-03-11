import socket
import time

import netbytes

MASK32 = 0xFFFFFFFF
long_size = 8

OK = "OK"
CONNECTION_CLOSED = "Соединение с сервером потеряно"

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
        self.timeout = 30
        self.message_timeout = 0.5

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

    def reset_timeout(self, is_message = False):
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
            if b'\n' in self._read_buffer:
                line, _, rest = self._read_buffer.partition(b'\n')
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
        return buffer if len(buffer) == num_bytes else None

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
            else:
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