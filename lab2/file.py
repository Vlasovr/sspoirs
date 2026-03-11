import os
import time
import netio
import cnsl
import shlex
import netbytes
from typing import Dict
from cnsl import LogTag
from neterror import CommandCancel
from neterror import ServerError
from  neterror import ConnectionClosed
from netio import NetConnection, UdpConnection
from pogress_tracker import ProgressTracker

DEFAULT_CHUNK_SIZE = 256 * netbytes.Size.KILOBYTE
FILES_DIR = "files"
UNCONFIRMED_FILENAME= "Неподтвержденный-файл"
LAST_UPLOAD_SESSION: Dict[str, dict] | None = None
class UploadSessionKeys:
    IP = 'ip'
    FILENAME = 'filename'
    FILE_SIZE = 'file_size'
    RECEIVED = 'received'

os.makedirs(FILES_DIR, exist_ok=True)

def clear_last_session():
    global LAST_UPLOAD_SESSION
    try:
        filepath = os.path.join(FILES_DIR, UNCONFIRMED_FILENAME)
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError as e:
        cnsl.log(LogTag.ERROR, f"Ошибка при удалении временного файла: {e}")
    LAST_UPLOAD_SESSION = None

def prepare_load(tracker: ProgressTracker, byte_count, file_size):
    tracker.bytes = byte_count
    tracker.start(file_size)

def end_load(tracker: ProgressTracker):
    tracker.stop()

def start_new_session(ip, filename, file_size):
    global LAST_UPLOAD_SESSION
    LAST_UPLOAD_SESSION = {
        UploadSessionKeys.IP: ip,
        UploadSessionKeys.FILENAME: filename,
        UploadSessionKeys.FILE_SIZE: file_size,
        UploadSessionKeys.RECEIVED: 0
    }

def is_same_client(ip):
    global LAST_UPLOAD_SESSION
    return LAST_UPLOAD_SESSION and LAST_UPLOAD_SESSION[UploadSessionKeys.IP] == ip

def prepare_new_client(ip):
    if not is_same_client(ip):
        clear_last_session()

def get_received_size(ip, filename, file_size):
    global LAST_UPLOAD_SESSION
    if LAST_UPLOAD_SESSION:
        if (LAST_UPLOAD_SESSION[UploadSessionKeys.IP] == ip and
        LAST_UPLOAD_SESSION[UploadSessionKeys.FILENAME] == filename and
        LAST_UPLOAD_SESSION[UploadSessionKeys.FILE_SIZE] == file_size):
            return LAST_UPLOAD_SESSION[UploadSessionKeys.RECEIVED]
    return 0

def prepare_file(filepath, offset):
    mode = 'r+b' if os.path.exists(filepath) else 'wb'
    file = open(filepath, mode)
    file.seek(offset)
    return file

def finalize_download(temp_path, final_path):
    os.rename(temp_path, final_path)
    global LAST_UPLOAD_SESSION
    LAST_UPLOAD_SESSION = None

def validate_upload_command(message):
    try:
        parts = shlex.split(message)
        if len(parts) not in (2, 3):
            return None, None, "Неверный формат. Используйте: UPLOAD [имя_файла] \"путь-к-файлу\""
        if len(parts) == 3:
            _, filename, filepath = parts
        else:
            _, filepath = parts
            filename = os.path.basename(filepath.rstrip("/\\"))
        if not os.path.isfile(filepath):
            return None, None, f"Файл по пути '{filepath}' не найден."
        return filename, filepath, None
    except ValueError as e:
        return None, None, f"Ошибка разбора команды: {e}"

def validate_download_command(message):
    parts = shlex.split(message)
    if len(parts) not in (2, 3):
        return None, None, "Неверный формат. Используйте: DOWNLOAD [имя_файла] \"путь-к-файлу-на-сервере\""
    if len(parts) == 3:
        _, filename, filepath = parts
    else:
        _, filepath = parts
        filename = os.path.basename(filepath.rstrip("/\\"))
    create_result = can_create_file(filename)
    if create_result != netio.OK:
        return None, None, create_result
    return filename, filepath, None

def can_create_file(filename):
    try:
        filepath = os.path.join(FILES_DIR, filename)
        with open(filepath, "x"):
            pass
        os.remove(filepath)
        return netio.OK
    except FileExistsError:
        return "Файл с таким названием уже существует"
    except PermissionError:
        return "Нет прав для создания файла"
    except OSError as e:
        return f"Невозможно создать файл: {e.strerror}"

def can_open_file(filepath, mode):
    try:
        with open(filepath, mode):
            pass
        return netio.OK
    except FileExistsError:
        return "Файл с таким названием уже существует"
    except PermissionError:
        return "Нет прав на доступ к файлу"
    except OSError as e:
        return f"Не удалось открыть файл: {e.strerror}"


def handle_sever_download(conn: NetConnection, filepath):
    if not os.path.dirname(filepath):
        filepath = os.path.join(FILES_DIR, filepath)
    if not os.path.isfile(filepath):
        conn.send_status(f"Файл по пути '{filepath}' не найден.")
        return
    filename = os.path.basename(filepath)
    status = can_open_file(filepath, "rb")
    conn.send_status(status)
    if status == netio.OK:
        return upload(conn, filepath, filename)


def handle_sever_upload(conn: NetConnection, filename):
    status = can_create_file(filename)
    conn.send_status(status)
    if status == netio.OK:
        return download(conn, filename)

def handle_client_upload(conn: NetConnection, message):
    filename, filepath, error = validate_upload_command(message)
    if error:
        cnsl.log(LogTag.ERROR, error)
        raise CommandCancel
    status = can_open_file(filepath, "r+b")
    if status != netio.OK:
        cnsl.log(LogTag.ERROR, status)
        raise CommandCancel
    conn.send_command(f"{netio.Commands.UPLOAD} {filename}")
    status = conn.get_status()
    if status != netio.OK:
        if status == netio.CONNECTION_CLOSED:
            raise ConnectionClosed
        print(f"⏺ Ошибка: {status}")
        raise ServerError
    filename = os.path.basename(filepath.rstrip("/\\"))
    upload(conn, filepath, filename)

def handle_client_download(conn: NetConnection, message):
    filename, filepath, error = validate_download_command(message)
    if error:
        cnsl.log(LogTag.ERROR, error)
        raise CommandCancel
    conn.send_command(f"{netio.Commands.DOWNLOAD} {filepath}")
    status = conn.get_status()
    if status != netio.OK:
        if status == netio.CONNECTION_CLOSED:
            raise ConnectionClosed
        print(f"⏺ Ошибка: {status}")
        raise ServerError
    download(conn, filename)


def receive_file_chunks(file, conn: NetConnection, total_size, tracker: ProgressTracker):
    bytes_left = total_size - tracker.bytes
    received = tracker.bytes
    while bytes_left > DEFAULT_CHUNK_SIZE:
        chunk = conn.r_exact(DEFAULT_CHUNK_SIZE)
        if not chunk:
            return False
        file.write(chunk)
        received += len(chunk)
        bytes_left -= len(chunk)
        LAST_UPLOAD_SESSION[UploadSessionKeys.RECEIVED] = received
        tracker.bytes = received

    if 0 < bytes_left <= DEFAULT_CHUNK_SIZE:
        chunk = conn.r_exact(bytes_left)
        if chunk:
            file.write(chunk)
            received += len(chunk)
            bytes_left -= len(chunk)
            LAST_UPLOAD_SESSION[UploadSessionKeys.RECEIVED] = received
            tracker.bytes = received

    return bytes_left == 0

def send_file_chunks(file, conn: NetConnection, chunk_size, file_size,  tracker: ProgressTracker):
    bytes_sent = tracker.bytes
    while bytes_sent < file_size:
        chunk = file.read(chunk_size)
        if not chunk:
            break
        conn.w_data(chunk)
        bytes_sent += len(chunk)
        tracker.bytes = bytes_sent

    return bytes_sent >= file_size

def download(conn: NetConnection, filename):
    conn.w_long(DEFAULT_CHUNK_SIZE)
    file_size = conn.r_long()
    if not file_size:
        msg = "Не удалось получить размер файла"
        cnsl.log(LogTag.INFO, msg)
        return msg
    ip = conn.get_addr()[0]
    received = get_received_size(ip, filename, file_size)
    start_size = received

    if isinstance(conn, UdpConnection):
        conn.timeout = conn.DEFAULT_TIMEOUT

    if received != 0:
        cnsl.log(LogTag.INFO, f"Возобновление загрузки файла {filename}")
    else:
        clear_last_session()
        start_new_session(ip, filename, file_size)
        cnsl.log(LogTag.INFO, f"Начало загрузки файла {filename}")

    filepath = os.path.join(FILES_DIR, UNCONFIRMED_FILENAME)
    final_path = os.path.join(FILES_DIR, filename)
    start_time = time.time()
    conn.w_long(received)

    tracker = ProgressTracker()
    prepare_load(tracker, received, file_size)
    try:
        with prepare_file(filepath, received) as file:
            success = receive_file_chunks(file, conn, file_size, tracker)
    finally:
        end_load(tracker)

    if success:
        finalize_download(filepath, final_path)
        speed = netbytes.calculate_speed(start_time, time.time(), file_size - start_size)
        result_str = f"Файл {filename} успешно загружен. Скорость: {speed}"
        cnsl.log(LogTag.SUCCESS, f"{result_str}")
    else:
        result_str = f"Ошибка при загрузке файла."
        cnsl.log(LogTag.ERROR, f"{result_str}")

    return result_str

def upload(conn: NetConnection, filepath, filename):
    chunk_size = conn.r_long()
    if chunk_size is None:
        msg = f"Не удалось получить размер чанка."
        cnsl.log(LogTag.INFO, msg)
        return msg
    file_size = os.path.getsize(filepath)
    conn.w_long(file_size)
    bytes_sent = conn.r_long()
    if bytes_sent is None:
        msg = f"Не удалось получить количество переданых данных."
        cnsl.log(LogTag.INFO, msg)
        return msg

    if isinstance(conn, UdpConnection):
        conn.timeout = conn.DEFAULT_TIMEOUT

    cnsl.log(LogTag.INFO, f"Отправка файла '{filename}' ({netbytes.human_readable_size(file_size-bytes_sent)})...")
    start_time = time.time()
    start_offset = bytes_sent

    tracker = ProgressTracker()
    prepare_load(tracker, bytes_sent, file_size)
    try:
        with prepare_file(filepath, start_offset) as file:
            success = send_file_chunks(file, conn, chunk_size, file_size, tracker)
    finally:
        end_load(tracker)

    if success:
        speed = netbytes.calculate_speed(start_time, time.time(), file_size - start_offset)
        result_str = f"Файл {filename} успешно отправлен. Скорость: {speed}"
        cnsl.log(LogTag.SUCCESS, f"{result_str}")
    else:
        result_str = f"Не удалось прочитать данные из файла."
        cnsl.log(LogTag.ERROR, f"{result_str}")
    return result_str
