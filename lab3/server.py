import select
import socket
import datetime
import netio
import cnsl
import cnsl_parser
from file import FileServer
from file_session import DownloadSession
from neterror import ClientDisconnected, ConnectionClosed, FileError
from cnsl import LogTag
from netio import TcpConnection

inputs = []
tcp_clients = {}

def configure_keepalive(sock, idle=30, interval=10, count=3):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
    elif hasattr(socket, "TCP_KEEPALIVE"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, idle)
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
    if hasattr(socket, "TCP_KEEPCNT"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, count)
    if hasattr(socket, "SIO_KEEPALIVE_VALS"):
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, idle * 1000, interval * 1000))

def start_server():
    cnsl.LOG_TYPE = cnsl.SERVER_TYPE
    host, port = cnsl_parser.get_args()
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.bind((host, port))
    tcp_sock.listen()
    tcp_sock.setblocking(False)

    cnsl.log(LogTag.SUCCESS, f"Сервер запущен на {host}:{port}")
    FileServer.clear_sessions()

    inputs.append(tcp_sock)

    while True:
        readable, _, _ = select.select(inputs, [], [], 0)
        for sock in readable:
            if sock is tcp_sock:
                client, addr = tcp_sock.accept()
                configure_keepalive(client)
                client.setblocking(False)
                client.settimeout(0.1)
                conn = netio.TcpConnection(client)
                add_new(conn)
                tcp_clients[client] = conn
                cnsl.log(LogTag.PLUS, f"Клиент {addr} подключен.")
            else:
                conn = tcp_clients[sock]
                try:
                    if conn:
                        handle_client_tcp(conn)
                        if conn.has_session:
                            inputs.remove(sock)
                except ConnectionClosed:
                    inputs.remove(sock)
                    end_session(conn)
        resume_sessions()

def end_session(conn):
    sock = conn.sock
    del tcp_clients[sock]
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except socket.error:
        pass
    sock.close()
    print_client_disconnect(conn.get_addr())

def add_new(conn):
    inputs.append(conn.sock)
    conn.send_status(netio.OK)
    conn.has_session = False

def resume_sessions():
    for s in list(FileServer.file_sessions):
        try:
            if not s.resume():
               s.conn.w_line(s.conclusion(True))
               if s in FileServer.file_sessions:
                   FileServer.file_sessions.remove(s)
               add_new(s.conn)
            continue
        except FileError:
            s.conn.w_line(s.conclusion(False))
        except socket.timeout:
            try:
                cnsl.log(LogTag.INFO, f"Время ожидания клиента {s.conn.get_addr()} истекло. Соединение закрыто.")
                s.conn.w_line("Время ожидания истекло.")
            except socket.error:
                pass
        except socket.error as e:
            try:
                cnsl.log(LogTag.ERROR, f"{s.conn.get_addr()} " + str(e))
                s.conn.w_line(str(e))
            except socket.error:
                pass
        if isinstance(s, DownloadSession):
            FileServer.save_session(s)
        if s in FileServer.file_sessions:
            FileServer.file_sessions.remove(s)
        end_session(s.conn)

def handle_client_tcp(conn):
    try:
        handle_client_command_tcp(conn)
        return
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
    raise ConnectionClosed

def handle_client_command_tcp(conn):
    data = conn.r_line()
    if not data:
        raise ClientDisconnected
    cnsl.log(LogTag.INFO, f"Команда от клиента {conn.get_addr()}: {data}")
    handle_client_command(conn, data)
    if not conn.has_session:
        conn.send_status(netio.OK)

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
