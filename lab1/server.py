import socket
import datetime
import file
import netio
import cnsl
import netstat
from neterror import ClientDisconnected
from cnsl import LogTag

HOST = '25.30.102.155'
PORT = 50505

def start_server():
    cnsl.LOG_TYPE = cnsl.SERVER_TYPE
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((HOST, PORT))
        server.listen()
        cnsl.log(LogTag.SUCCESS, f"Сервер запущен на {HOST}:{PORT}")
        file.clear_last_session()
        while True:
            cnsl.log(LogTag.INFO, "Ожидание подключения клиента...")
            conn, addr = server.accept()
            conn.settimeout(30)
            file.prepare_new_client(conn.getpeername()[0])
            try:
                handle_client(conn, addr)
            except socket.timeout:
                try:
                    cnsl.log(LogTag.INFO, "Время ожидания истекло. Соединение закрыто.")
                    netio.w_line(conn, "Время ожидания истекло.")
                except socket.error:
                    pass
            except socket.error as e:
                try:
                    cnsl.log(LogTag.ERROR, e)
                    netio.w_line(conn, e)
                except socket.error:
                    pass
            except ClientDisconnected:
                cnsl.log(LogTag.INFO, f"Клиент {addr} закрыл соединение")
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except socket.error:
                pass
            conn.close()
            print_client_disconnect(addr)

def handle_client(conn, addr):
    cnsl.log(LogTag.PLUS, f"Клиент подключен: {addr}")
    with conn:
        while True:
            netstat.send_status(conn, netstat.OK)
            data = netio.r_line(conn)
            if not data:
                raise ClientDisconnected()
            cnsl.log(LogTag.INFO, f"Команда от клиента: {data}")
            command, argument = split_command(data)
            response = handle_command(command, argument, conn)
            if response:
                netio.w_line(conn, response)

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
        handle_close(conn)
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
    return argument

def handle_close(conn):
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
