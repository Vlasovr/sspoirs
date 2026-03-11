import threading
import time
import socket
import file
import netio
import netregex
import cnsl
import netstat
from cnsl import LogTag
from neterror import CommandCancel, ConnectionClosed
from neterror import ServerError

QUIT_STR = "quit"
BACK_STR = "back"
connecting = True

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
        if connected(client_socket):
            result = (True, LogTag.SUCCESS, f"Подключен к серверу {server_ip}:{server_port}")
        else:
            result = (False, LogTag.ERROR, "Сервер занят.")
    except ConnectionRefusedError:
        result = (False, LogTag.ERROR, "Соединение отклонено сервером. Проверьте IP и порт.")
    except TimeoutError:
        result = (False, LogTag.ERROR, "Превышено время ожидания подключения к серверу.")
    except socket.gaierror:
        result = (False, LogTag.ERROR, "Невозможно разрешить имя хоста. Проверьте IP-адрес.")
    except socket.error as e:
        result = (False, LogTag.ERROR, f"Ошибка сокета: {e}")
    except Exception as e:
        result = (False, LogTag.ERROR, f"Неизвестная ошибка: {e}")
    connecting = False
    dot_thread.join()
    cnsl.clear()
    success, tag, message = result
    cnsl.log(tag, message)
    return success

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
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM)

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
    status = netstat.get_status(conn)
    return status == netstat.OK

def communicate_with_server(conn):
    conn.settimeout(30)
    should_ask_status = False
    while True:
        if should_ask_status:
            if not connected(conn):
                break
        else:
            should_ask_status = True

        try:
            message = process_user_input()
            if message == BACK_STR:
                break

            command, *_ = message.strip().split(maxsplit=1)
            command = command.upper()

            if command == netio.Commands.UPLOAD:
                file.handle_client_upload(conn, message)
            elif command == netio.Commands.DOWNLOAD:
                file.handle_client_download(conn, message)
            else:
                netio.w_line(conn, message)
            response = netio.r_line(conn)
            if response:
                print(f"⏺ {response.rstrip()}")
            else:
                break
        except CommandCancel:
            should_ask_status = False
            pass
        except ServerError:
            pass

def main():
    cnsl.clear()
    file.clear_last_session()
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
        client_socket = create_socket()
        if not connect_to_server(client_socket, server_ip, server_port):
            continue

        try:
            communicate_with_server(client_socket)
        except ConnectionClosed:
            pass
        except socket.timeout:
            cnsl.log(LogTag.INFO, "Время ожидания истекло. Соединение закрыто.")
        except socket.error as e:
            cnsl.log(LogTag.ERROR, e)
        try:
            client_socket.shutdown(socket.SHUT_RDWR)
        except socket.error:
            pass
        close_connection(client_socket)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("")
        pass

# UPLOAD /mnt/storage/SPOIRS/lab1.zip
# 25.17.44.54