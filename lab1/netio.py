import bytes

long_size = 8
int_size = 4
_line_buffers = {}

class Commands:
    ECHO = "ECHO"
    TIME = "TIME"
    CLOSE = "CLOSE"
    UPLOAD = "UPLOAD"
    DOWNLOAD = "DOWNLOAD"

def r_long(conn):
    data = b''
    while len(data) < long_size:
        chunk = conn.recv(long_size - len(data))
        if not chunk:
            return None
        data += chunk
    return int.from_bytes(data, 'big')

def r_int(conn):
    data = b''
    while len(data) < int_size:
        chunk = conn.recv(int_size - len(data))
        if not chunk:
            return None
        data += chunk
    return int.from_bytes(data, 'big')

def r_line(conn):
    buffer = _line_buffers.get(conn, b"")
    while True:
        try:
            if b'\n' in buffer:
                line, _, rest = buffer.partition(b'\n')
                _line_buffers[conn] = rest
                return line.decode(errors="ignore").strip()
            data = conn.recv(bytes.Size.KILOBYTE)
            if not data:
                _line_buffers.pop(conn, None)
                return None
            buffer += data
        except UnicodeDecodeError:
            _line_buffers.pop(conn, None)
            return None

def r_exact(conn, num_bytes):
    buffer = b""
    try:
        while len(buffer) < num_bytes:
            chunk = conn.recv(num_bytes - len(buffer))
            if not chunk:
                return None
            buffer += chunk
        return buffer if len(buffer) == num_bytes else None
    except UnicodeDecodeError:
        return None

def w_line(conn, data):
    conn.sendall((str(data) + "\n").encode())

def w_data(conn, data):
    conn.sendall(data)

def w_long(conn, long):
    w_data(conn, long.to_bytes(long_size, 'big'))
