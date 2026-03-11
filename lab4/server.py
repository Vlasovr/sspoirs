import os
import socket
import datetime
import tempfile
from concurrent.futures import ThreadPoolExecutor
import netio
import cnsl
import cnsl_parser
from file import FileServer
from neterror import ClientDisconnected
from cnsl import LogTag
from netio import TcpConnection

if os.name == 'nt':
    import msvcrt
    def _lock_file(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl
    def _lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

LOCK_PATH = os.path.join(tempfile.gettempdir(), "accept.lock")

MAX_THREADS = 5
LOCK_FILE = "/tmp/accept.lock"

def acquire_accept_lock():
    f = open(LOCK_PATH, "a+")
    _lock_file(f)
    return f

def release_accept_lock(f):
    try:
        _unlock_file(f)
    finally:
        f.close()

def start_server():
    cnsl.LOG_TYPE = cnsl.SERVER_TYPE
    FileServer.clear_sessions()
    host, port = cnsl_parser.get_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen()
        cnsl.log(LogTag.SUCCESS, f"Сервер запущен на {host}:{port}")

        with ThreadPoolExecutor(max_workers=MAX_THREADS) as pool:
            for _ in range(MAX_THREADS):
                pool.submit(accept_loop, server)

def accept_loop(server_sock: socket.socket):
    while True:
        lock_fd = acquire_accept_lock()
        try:
            client_sock, addr = server_sock.accept()
        finally:
            release_accept_lock(lock_fd)

        client_sock.settimeout(2)
        client_sock.setblocking(False)
        conn = TcpConnection(client_sock)
        conn.message_timeout = 20

        cnsl.log(LogTag.INFO, f"Клиент {conn.get_addr()} подключен.")
        handle_client_tcp(conn)

def handle_client_tcp(conn):
    try:
        while True:
            handle_client_command_tcp(conn)
    except socket.timeout:
        try:
            cnsl.log(LogTag.INFO, f"Время ожидания клиента {conn.get_addr()} истекло. Соединение закрыто.")
            conn.w_line("Время ожидания истекло.")
        except socket.error:
            pass
    except socket.error as e:
        try:
            cnsl.log(LogTag.ERROR, f"{conn.get_addr()} " + str(e))
            conn.w_line(str(e))
        except socket.error:
            pass
    except ClientDisconnected:
        cnsl.log(LogTag.INFO, f"Клиент {conn.get_addr()} закрыл соединение")
    sock = conn.sock
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except socket.error:
        pass
    sock.close()
    print_client_disconnect(conn.get_addr())

def handle_client_command_tcp(conn):
    conn.send_status(netio.OK)
    data = conn.r_line()
    if not data:
        raise ClientDisconnected
    cnsl.log(LogTag.INFO, f"Команда от клиента {conn.get_addr()}: {data}")
    handle_client_command(conn, data)

def handle_client_command(conn, data):
    command, argument = split_command(data)
    response = handle_command(command, argument, conn)
    if response:
        conn.w_line(response)

def handle_command(command, argument, conn):
    if command == netio.Commands.ECHO:
        return handle_echo(argument)
    elif command == netio.Commands.TIME:
        return handle_time()
    elif command == netio.Commands.UPLOAD:
        return FileServer.handle_upload(conn, argument)
    elif command == netio.Commands.DOWNLOAD:
        return FileServer.handle_download(conn, argument)
    elif command == netio.Commands.CLOSE:
        if isinstance(conn, TcpConnection):
            handle_close()
        else:
            return f"Команда \"{netio.Commands.CLOSE}\" применима только для TCP"
    else:
        return handle_unknown(command)

def split_command(data):
    parts = data.split(maxsplit=1)
    command = parts[0].upper()
    argument = parts[1] if len(parts) > 1 else ""
    return command, argument

def handle_time():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def handle_echo(argument):
    if not argument:
        return "Команда ECHO требует аргумент для отправки."
    return argument

def handle_close():
    raise ClientDisconnected

def handle_unknown(command):
    return f"Неизвестная команда: {command}"

def close_connection_message():
    return "Соединение закрывается..."

def print_client_disconnect(addr):
    cnsl.log(LogTag.MINUS, f"Клиент отключён: {addr}")

if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        print("")
        pass
