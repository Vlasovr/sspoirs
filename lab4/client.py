import socket
import threading
import time

import cnsl
import cnsl_parser
import netio
import netregex
from cnsl import LogTag
from file import FileClient
from neterror import CommandCancel, ConnectionClosed, ServerError

QUIT_STR = "quit"
BACK_STR = "back"
connecting = True
addr = ("", 0)


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


def show_connecting_dots(interval=1.0):
    cnsl.clear()
    cnsl.print_inline("Подключение")
    while connecting:
        print(".", end="", flush=True)
        time.sleep(interval)


def connect_to_server(client_socket, server_ip, server_port):
    global connecting
    connecting = True
    dot_thread = threading.Thread(target=show_connecting_dots, daemon=True)
    dot_thread.start()
    try:
        client_socket.settimeout(0.1)
        conn = netio.UdpConnection(client_socket, (server_ip, server_port), timeout=30)
        conn.message_timeout = 1
        result = (conn, LogTag.SUCCESS, f"Подключен к серверу {server_ip}:{server_port}")
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(addr)
    return sock


def close_connection(client_socket):
    client_socket.close()
    cnsl.log(LogTag.INFO, "Соединение закрыто.")


def quit_program():
    cnsl.log(LogTag.MINUS, "Выход из программы...")
    exit(0)


def prompt_retry(message: str) -> bool:
    retry = input(message).strip().lower()
    if retry == QUIT_STR:
        quit_program()
    return retry in ["y", "д"]


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
    elif command == netio.Commands.CLOSE:
        conn.send_command(message)
        return False
    else:
        conn.send_command(message)

    response = conn.r_line()
    if response:
        print(f"⏺ {response.rstrip()}")
        return True
    return False


def handle_server_udp(ip, port):
    sock = create_socket()
    conn = connect_to_server(sock, ip, port)
    if not conn:
        close_connection(sock)
        return

    try:
        while True:
            try:
                if not communicate_with_server(conn):
                    break
            except CommandCancel:
                pass
            except ServerError:
                pass
    except ConnectionClosed:
        cnsl.log(LogTag.ERROR, "Соединение с сервером разорвано.")
    except socket.timeout:
        cnsl.log(LogTag.ERROR, "Время ожидания истекло.")
    except socket.gaierror:
        cnsl.log(LogTag.ERROR, "Невозможно разрешить имя хоста. Проверьте IP-адрес.")
    except socket.error as e:
        cnsl.log(LogTag.ERROR, f"Ошибка сокета: {e}")
    except Exception as e:
        cnsl.log(LogTag.ERROR, f"Неизвестная ошибка: {e}")
    finally:
        close_connection(sock)


def main():
    global addr
    cnsl.clear()
    FileClient.clear_sessions()
    cnsl.LOG_TYPE = cnsl.CLIENT_TYPE
    addr = cnsl_parser.get_args()
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
        handle_server_udp(server_ip, server_port)
        cnsl.clear()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("")
        pass
