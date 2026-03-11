import socket
import datetime
import file
import netio
import cnsl
import cnsl_parser
from neterror import ClientDisconnected
from cnsl import LogTag
from netio import UdpConnection, TcpConnection

def start_server():
    cnsl.LOG_TYPE = cnsl.SERVER_TYPE
    host, port = cnsl_parser.get_args()
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.bind((host, port))
    tcp_sock.listen()
    tcp_sock.setblocking(False)

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind((host, port))
    udp_sock.setblocking(False)

    cnsl.log(LogTag.SUCCESS, f"Сервер запущен на {host}:{port}")
    file.clear_last_session()

    while True:
        handle_client_tcp(tcp_sock)
        handle_client_udp(udp_sock)

def handle_client_tcp(sock):
    sock.settimeout(1)
    try:
        client, addr = sock.accept()
    except socket.timeout:
        return
    client.settimeout(30)
    cnsl.log(LogTag.PLUS, f"[TCP] Клиент подключен: {addr}")
    conn = netio.TcpConnection(client)
    file.prepare_new_client(conn.get_addr()[0])
    try:
        handle_client_commands_tcp(conn)
    except socket.timeout:
        try:
            cnsl.log(LogTag.INFO, "Время ожидания истекло. Соединение закрыто.")
            conn.w_line("Время ожидания истекло.")
        except socket.error:
            pass
    except socket.error as e:
        try:
            cnsl.log(LogTag.ERROR, str(e))
            conn.w_line(str(e))
        except socket.error:
            pass
    except ClientDisconnected:
        cnsl.log(LogTag.INFO, f"Клиент {addr} закрыл соединение")
    finally:
        try:
            client.shutdown(socket.SHUT_RDWR)
        except socket.error:
            pass
        client.close()
        print_client_disconnect(addr)

def handle_client_udp(sock):
    conn = UdpConnection(sock, None, 1)
    try:
        data = conn.r_line()
        if not data:
            return
        cnsl.log(LogTag.PLUS, f"[UDP] Команда от клиента {conn.get_addr()}: {data}")
    except socket.error:
        return
    try:
        conn.timeout = 3
        file.prepare_new_client(conn.get_addr()[0])
        handle_client_command(conn, data)
    except socket.timeout:
        cnsl.log(LogTag.INFO, "Время ожидания истекло")
    except socket.error as e:
        cnsl.log(LogTag.ERROR, str(e))

def handle_client_commands_tcp(conn):
    while True:
        conn.send_status(netio.OK)
        data = conn.r_line()
        if not data:
            raise ClientDisconnected()
        cnsl.log(LogTag.INFO, f"Команда от клиента: {data}")
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
        return file.handle_sever_upload(conn, argument)
    elif command == netio.Commands.DOWNLOAD:
        return file.handle_sever_download(conn, argument)
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
    raise ClientDisconnected()

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
