import threading
import time
import socket
import cnsl_parser
import netbytes
import netio
import netregex
import cnsl
from cnsl import LogTag
from neterror import CommandCancel, ConnectionClosed
from neterror import ServerError
from netio import TcpConnection
from file import FileClient

QUIT_STR = "quit"
BACK_STR = "back"
connecting = True

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

def prompt_for_ip():
    while True:
        ip = input("Введите IP-адрес сервера: ").strip()
        if ip.lower() == QUIT_STR:
            quit_program()
        if netregex.is_valid_ip(ip):
            return ip
        cnsl.log(LogTag.WARNING, netregex.WRONG_IP_MESSAGE)

def prompt_for_port():
    while True:
        port = input("Введите порт сервера (или 'back', чтобы изменить IP-адрес): ").strip()
        if port.lower() == QUIT_STR:
            quit_program()
        if port.lower() == BACK_STR:
            return BACK_STR
        if netregex.is_valid_port(port):
            return int(port)
        cnsl.log(LogTag.WARNING, netregex.WRONG_PORT_MESSAGE)


def get_server_info():
    while True:
        ip = prompt_for_ip()
        while True:
            port = prompt_for_port()
            if port == BACK_STR:
                break
            return ip, port

def show_connecting_dots(interval=1.5):
    cnsl.clear()
    cnsl.print_inline("Подключение")
    while connecting:
        print(".", end="", flush=True)
        time.sleep(interval)


def connect_to_server(client_socket, server_ip, server_port, timeout=10):
    global connecting
    connecting = True
    dot_thread = threading.Thread(target=show_connecting_dots, daemon=True)
    dot_thread.start()
    try:
        client_socket.settimeout(timeout)
        client_socket.connect((server_ip, server_port))
        configure_keepalive(client_socket)
        tcp_conn = TcpConnection(client_socket)
        if connected(tcp_conn):
            client_socket.settimeout(0.1)
            tcp_conn.message_timeout = 1
            result = (tcp_conn, LogTag.SUCCESS, f"Подключен к серверу {server_ip}:{server_port}")
        else:
            result = (None, LogTag.ERROR, "Сервер занят.")
    except ConnectionRefusedError:
        result = (None, LogTag.ERROR, "Соединение отклонено сервером. Проверьте IP и порт.")
    except TimeoutError:
        result = (None, LogTag.ERROR, "Превышено время ожидания подключения к серверу.")
    except socket.gaierror:
        result = (None, LogTag.ERROR, "Невозможно разрешить имя хоста. Проверьте IP-адрес.")
    except socket.error as e:
        result = (None, LogTag.ERROR, f"Ошибка сокета: {e}")
    except Exception as e:
        result = (None, LogTag.ERROR, f"Неизвестная ошибка: {e}")
    connecting = False
    dot_thread.join()
    cnsl.clear()
    conn, tag, message = result
    cnsl.log(tag, message)
    return conn

def process_user_input():
    while True:
        message = input("Введите команду (или 'back', чтобы вернуться): ")
        if message.lower() == QUIT_STR:
            quit_program()
        if message.lower() == BACK_STR:
            return BACK_STR
        if not message.strip():
            continue
        return message

def create_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((cnsl_parser.DEFAULT_IP, cnsl_parser.DEFAULT_PORT))
    return sock

def close_connection(client_socket):
    client_socket.close()
    print_connection_closed()

def print_connection_closed():
    cnsl.log(LogTag.INFO, "Соединение закрыто.")

def quit_program():
    cnsl.log(LogTag.MINUS, "Выход из программы...")
    exit(0)

def prompt_retry(message: str) -> bool:
    retry = input(message).strip().lower()
    if retry == QUIT_STR:
        quit_program()
    return retry in ['y', 'д']

def connected(conn):
    status = conn.get_status()
    return status == netio.OK

def communicate_with_server_tcp(conn):
    should_ask_status = False
    while True:
        if should_ask_status:
            if not connected(conn):
                break
        else:
            should_ask_status = True
        try:
            if not communicate_with_server(conn):
                return
        except CommandCancel:
            should_ask_status = False
            pass
        except ServerError:
            pass

def communicate_with_server(conn):
    message = process_user_input()
    if message == BACK_STR:
        return False

    command, *_ = message.strip().split(maxsplit=1)
    command = command.upper()

    if command == netio.Commands.UPLOAD:
        FileClient.handle_upload(conn, message)
    elif command == netio.Commands.DOWNLOAD:
        FileClient.handle_download(conn, message)
    else:
        conn.send_command(message)
    response = conn.r_line()
    if response:
        print(f"⏺ {response.rstrip()}")
    else:
        return False
    return True


def handle_server_tcp(ip, port):
    sock = create_socket()
    conn = connect_to_server(sock, ip, port)
    if not conn:
        return
    try:
        communicate_with_server_tcp(conn)
    except ConnectionClosed:
        pass
    except socket.timeout:
        cnsl.log(LogTag.INFO, "Время ожидания истекло. Соединение закрыто.")
    except socket.error as e:
        cnsl.log(LogTag.ERROR, e)
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except socket.error:
        pass
    close_connection(sock)

def main():
    cnsl.clear()
    FileClient.clear_sessions()
    cnsl.LOG_TYPE = cnsl.CLIENT_TYPE
    cnsl.log(LogTag.PLUS, f"Клиент запущен. Для выхода введите '{QUIT_STR}'")
    server_ip, server_port = None, None
    while True:
        if server_ip and server_port:
            if not prompt_retry(f"Повторить подключениe к {server_ip}:{server_port}? (y/n): "):
                cnsl.clear()
                server_ip, server_port = get_server_info()
        else:
            server_ip, server_port = get_server_info()
        cnsl.clear()
        handle_server_tcp(server_ip, server_port)
        cnsl.clear()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("")
        pass

# UPLOAD /mnt/storage/SPOIRS/lab1.zip
# 192.168.100.46
# download lab1.zip
