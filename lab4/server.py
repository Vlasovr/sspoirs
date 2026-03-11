import datetime
import socket
import threading
import time

import cnsl
import cnsl_parser
import netio
from cnsl import LogTag
from file import FileServer
from neterror import ClientDisconnected

active_sessions = {}
active_sessions_lock = threading.Lock()
SESSION_TIMEOUT = 60


def start_server():
    cnsl.LOG_TYPE = cnsl.SERVER_TYPE
    FileServer.clear_sessions()
    host, port = cnsl_parser.get_args()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.settimeout(0.1)

        cnsl.log(LogTag.SUCCESS, f"Сервер запущен на {host}:{port}")

        while True:
            clear_finished_sessions()
            addr = netio.peek_next_sender(server, netio.UdpConnection.TOTAL_SIZE)
            if not addr:
                continue

            with active_sessions_lock:
                if addr in active_sessions:
                    should_wait = True
                else:
                    should_wait = False

                    thread = threading.Thread(
                        target=handle_client_session,
                        args=(server, addr),
                        daemon=True,
                    )
                    active_sessions[addr] = thread
                    thread.start()
                    cnsl.log(LogTag.PLUS, f"[UDP] Запущена сессия клиента {addr}")
            if should_wait:
                time.sleep(0.001)


def clear_finished_sessions():
    with active_sessions_lock:
        finished = [addr for addr, thread in active_sessions.items() if not thread.is_alive()]
        for addr in finished:
            active_sessions.pop(addr, None)


def handle_client_session(server_sock, addr):
    conn = netio.UdpConnection(server_sock, addr, timeout=SESSION_TIMEOUT)
    conn.message_timeout = 1

    try:
        while True:
            data = conn.r_line()
            if not data:
                raise ClientDisconnected
            cnsl.log(LogTag.INFO, f"Команда от клиента {addr}: {data}")
            handle_client_command(conn, data)

    except socket.timeout:
        try:
            cnsl.log(LogTag.INFO, f"Время ожидания клиента {addr} истекло. Сессия закрыта.")
            conn.w_line("Время ожидания истекло.")
        except socket.error:
            pass
    except socket.error as e:
        try:
            cnsl.log(LogTag.ERROR, f"{addr} {e}")
            conn.w_line(str(e))
        except socket.error:
            pass
    except ClientDisconnected:
        cnsl.log(LogTag.INFO, f"Клиент {addr} завершил сессию")
    finally:
        with active_sessions_lock:
            active_sessions.pop(addr, None)
        print_client_disconnect(addr)


def handle_client_command(conn, data):
    command, argument = split_command(data)
    response = handle_command(command, argument, conn)
    if response:
        conn.w_line(response)


def handle_command(command, argument, conn):
    if command == netio.Commands.ECHO:
        return handle_echo(argument)
    if command == netio.Commands.TIME:
        return handle_time()
    if command == netio.Commands.UPLOAD:
        return FileServer.handle_upload(conn, argument)
    if command == netio.Commands.DOWNLOAD:
        return FileServer.handle_download(conn, argument)
    if command == netio.Commands.CLOSE:
        handle_close()
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


def print_client_disconnect(addr):
    cnsl.log(LogTag.MINUS, f"Клиент отключён: {addr}")


if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        print("")
        pass
