import os
import threading
import time
import netio
import cnsl
import shlex
import netbytes
from cnsl import LogTag
from file_session import UploadSession, DownloadSession
from neterror import CommandCancel, FileError
from neterror import ServerError
from  neterror import ConnectionClosed
from netio import NetConnection
from pogress_tracker import ProgressTracker

DEFAULT_CHUNK_SIZE = 64 * netbytes.Size.KILOBYTE
FILES_DIR = "files"
os.makedirs(FILES_DIR, exist_ok=True)

class File:
    UNCONFIRMED_FILENAME = "Неподтвержденный-файл"

    @classmethod
    def can_create_file(cls, filename):
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

    @staticmethod
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

    @staticmethod
    def prepare_file(filepath, offset):
        mode = 'rb' if os.path.exists(filepath) else 'wb'
        file = open(filepath, mode)
        file.seek(offset)
        return file

    @classmethod
    def clear_sessions(cls):
        try:
            for filename in os.listdir(FILES_DIR):
                if filename.startswith(File.UNCONFIRMED_FILENAME):
                    cls.delete_file(filename)
        except OSError as e:
            cnsl.log(LogTag.ERROR, f"Ошибка при удалении временных файлов: {e}")

    @staticmethod
    def delete_file(filename):
        filepath = os.path.join(FILES_DIR, filename)
        try:
            os.remove(filepath)
        except OSError as e:
            cnsl.log(LogTag.ERROR, f"Ошибка при удалении файла {filename}: {e}")

    @classmethod
    def finalize_download(cls, temp_path, final_path):
        os.rename(temp_path, final_path)

    @staticmethod
    def generate_free_filename():
        base_name = File.UNCONFIRMED_FILENAME
        candidate = base_name
        index = 1

        while os.path.exists(os.path.join(FILES_DIR, candidate)):
            candidate = f"{base_name}-{index}"
            index += 1

        return candidate

class FileServer(File):
    file_locks = {}
    lock_f = threading.Lock()
    lock_s = threading.Lock()
    stopped_sessions: [(time, DownloadSession)] = []
    clear_timeout = 20

    @classmethod
    def handle_download(cls, conn: NetConnection, filepath):
        if not os.path.dirname(filepath):
            filepath = os.path.join(FILES_DIR, filepath)
        if not os.path.isfile(filepath):
            conn.send_status(f"Файл по пути '{filepath}' не найден.")
            cnsl.log(LogTag.ERROR, f"{conn.get_addr()} Файл по пути '{filepath}' не найден.")
            return
        filename = os.path.basename(filepath)
        status = cls.can_open_file(filepath, "rb")
        conn.send_status(status)
        if status == netio.OK:
            return cls.upload(conn, filepath, filename)
        else:
            cnsl.log(LogTag.INFO, f"{conn.get_addr()} {status}")

    @classmethod
    def lock_file(cls, filename, owner_id):
        with cls.lock_f:
            if filename not in cls.file_locks:
                cls.file_locks[filename] = owner_id
                return netio.OK
            if cls.file_locks[filename] == owner_id:
                return netio.OK
            return "Файл с таким названием занят другим клиентом"

    @classmethod
    def release_lock(cls, filename, owner_id=None):
        with cls.lock_f:
            if filename not in cls.file_locks:
                return
            if owner_id is None or cls.file_locks[filename] == owner_id:
                cls.file_locks.pop(filename, None)

    @classmethod
    def can_create_file_server(cls, filename, owner_id):
        result = cls.can_create_file(filename)
        if result == netio.OK:
            return cls.lock_file(filename, owner_id)
        return result

    @classmethod
    def handle_upload(cls, conn: NetConnection, filename):
        status = cls.can_create_file_server(filename, conn.get_addr()[0])
        conn.send_status(status)
        if status == netio.OK:
            return cls.download(conn, filename)
        else:
            cnsl.log(LogTag.ERROR, f"{conn.get_addr()} {status}")

    @classmethod
    def save_session(cls, session):
        with cls.lock_s:
            cls.stopped_sessions.append((time.time() + cls.clear_timeout, session))

    @classmethod
    def get_uncompleted_session(cls, id, filename, size):
        now = time.time()
        result = None
        with cls.lock_s:
            for idx in range(len(cls.stopped_sessions) - 1, -1, -1):
                ts, session = cls.stopped_sessions[idx]
                if session.get_id() == id and session.filename == filename and session.file_size == size:
                    cls.stopped_sessions.pop(idx)
                    result = session
                else:
                    if ts <= now:
                        cls.stopped_sessions.pop(idx)
                        cls.release_lock(session.filename)
                        try:
                            os.remove(os.path.join(FILES_DIR, session.shadow_name))
                        except OSError:
                            pass
        return result

    @classmethod
    def upload(cls, conn: NetConnection, filepath, filename):
        chunk_size = conn.r_long()
        if chunk_size is None:
            msg = f"Не удалось получить размер чанка."
            cnsl.log(LogTag.INFO, f"{conn.get_addr()} {msg}")
            return msg
        file_size = os.path.getsize(filepath)
        conn.w_long(file_size)
        bytes_sent = conn.r_long()
        if bytes_sent is None:
            msg = f"Не удалось получить количество переданых данных."
            cnsl.log(LogTag.INFO, f"{conn.get_addr()} {msg}")
            return msg

        cnsl.log(LogTag.INFO,
                 f"{conn.get_addr()} Отправка файла '{filename}' ({netbytes.human_readable_size(file_size - bytes_sent)})...")

        file = cls.prepare_file(filepath, bytes_sent)
        upload_session = UploadSession(
            conn=conn,
            fd=file,
            filename=filename,
            chunk_size=chunk_size,
            file_size=file_size,
            bytes_sent=bytes_sent
        )
        try:
            while upload_session.resume():
                pass
            return upload_session.conclusion(True)
        except FileError:
            upload_session.conn.w_line(upload_session.conclusion(False))
            raise

    @classmethod
    def download(cls, conn: NetConnection, filename):
        should_release = True
        try:
            conn.w_long(DEFAULT_CHUNK_SIZE)
            file_size = conn.r_long()
            if not file_size:
                msg = "Не удалось получить размер файла"
                cnsl.log(LogTag.INFO, f"{conn.get_addr()} {msg}")
                return msg
            ip = conn.get_addr()[0]
            download_session = cls.get_uncompleted_session(ip, filename, file_size)
            received = 0

            if download_session:
                cnsl.log(LogTag.INFO, f"{conn.get_addr()} Возобновление загрузки файла {filename}")
                received = download_session.start_offset
                download_session.conn = conn
            else:
                cnsl.log(LogTag.INFO, f"{conn.get_addr()} Начало загрузки файла {filename}")
                temp_filename = cls.generate_free_filename()
                filepath = os.path.join(FILES_DIR, temp_filename)
                file = cls.prepare_file(filepath, received)
                download_session = DownloadSession(
                    conn=conn,
                    fd=file,
                    filename=filename,
                    shadow_name=temp_filename,
                    chunk_size=DEFAULT_CHUNK_SIZE,
                    file_size=file_size
                )
            conn.w_long(received)
            try:
                while download_session.resume():
                    pass
                return download_session.conclusion(True)
            except FileError:
                download_session.conn.w_line(download_session.conclusion(False))
                FileServer.save_session(download_session)
                should_release = False
                raise
            except Exception:
                FileServer.save_session(download_session)
                should_release = False
                raise
        finally:
            if should_release:
                cls.release_lock(filename)


class FileClient(File):
    download_session = None

    @classmethod
    def prepare_load(cls, tracker: ProgressTracker, conn, byte_count, file_size):
        tracker.bytes = byte_count
        tracker.start(file_size)
        conn.sock.settimeout(1)

    @classmethod
    def end_load(cls, tracker: ProgressTracker, conn):
        tracker.stop()
        conn.sock.settimeout(conn.DEFAULT_TIMEOUT)

    @classmethod
    def validate_upload_command(cls, message):
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

    @classmethod
    def validate_download_command(cls, message):
        try:
            parts = shlex.split(message)
        except ValueError:
            return None, None, "Неверный формат. Используйте: DOWNLOAD [имя_файла] \"путь-к-файлу-на-сервере\""

        if len(parts) not in (2, 3):
            return None, None, "Неверный формат. Используйте: DOWNLOAD [имя_файла] \"путь-к-файлу-на-сервере\""
        if len(parts) == 3:
            _, filename, filepath = parts
        else:
            _, filepath = parts
            filename = os.path.basename(filepath.rstrip("/\\"))
        create_result = cls.can_create_file(filename)
        if create_result != netio.OK:
            return None, None, create_result
        return filename, filepath, None

    @classmethod
    def handle_upload(cls, conn: NetConnection, message):
        filename, filepath, error = cls.validate_upload_command(message)
        if error:
            cnsl.log(LogTag.ERROR, error)
            raise CommandCancel
        status = cls.can_open_file(filepath, "r+b")
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
        cls.upload(conn, filepath, filename)

    @classmethod
    def handle_download(cls, conn: NetConnection, message):
        filename, filepath, error = cls.validate_download_command(message)
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
        cls.download(conn, filename)

    @classmethod
    def get_uncompleted_session(cls, id, filename, size):
        if cls.download_session:
            if (cls.download_session.get_id() == id
                    and cls.download_session.filename == filename
                    and cls.download_session.file_size == size):
                return cls.download_session
            else:
                cls.download_session = None
                cls.clear_sessions()

    @classmethod
    def upload(cls, conn: NetConnection, filepath, filename):
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

        cnsl.log(LogTag.INFO,
                 f"Отправка файла '{filename}' ({netbytes.human_readable_size(file_size - bytes_sent)})...")

        tracker = ProgressTracker()
        cls.prepare_load(tracker, conn, bytes_sent, file_size)
        file = cls.prepare_file(filepath, bytes_sent)
        upload_session = UploadSession(
            conn=conn,
            fd=file,
            filename=filename,
            chunk_size=chunk_size,
            file_size=file_size,
            bytes_sent=bytes_sent
        )
        try:
            while upload_session.resume():
                tracker.bytes = upload_session.bytes_sent
        finally:
            cls.end_load(tracker, conn)
        upload_session.conclusion(True)

    @classmethod
    def download(cls, conn: NetConnection, filename):
        conn.w_long(DEFAULT_CHUNK_SIZE)
        file_size = conn.r_long()
        if not file_size:
            msg = "Не удалось получить размер файла"
            cnsl.log(LogTag.INFO, msg)
            return msg
        ip = conn.get_addr()[0]
        received = 0

        session = cls.get_uncompleted_session(ip, filename, file_size)

        if session:
            cnsl.log(LogTag.INFO, f"Возобновление загрузки файла {filename}")
            received = session.start_offset
            cls.download_session.conn = conn
        else:
            cnsl.log(LogTag.INFO, f"Начало загрузки файла {filename}")
            temp_filename = cls.generate_free_filename()
            filepath = os.path.join(FILES_DIR, temp_filename)
            file = cls.prepare_file(filepath, received)
            cls.download_session = DownloadSession(
                conn=conn,
                fd=file,
                filename=filename,
                shadow_name=temp_filename,
                chunk_size=DEFAULT_CHUNK_SIZE,
                file_size=file_size
            )
        conn.w_long(received)
        tracker = ProgressTracker()
        cls.prepare_load(tracker, conn, received, file_size)
        try:
            while cls.download_session.resume():
                tracker.bytes = cls.download_session.offset
        finally:
            cls.end_load(tracker, conn)
        cls.download_session.conclusion(True)
        cls.download_session = None
