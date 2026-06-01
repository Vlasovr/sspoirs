import hashlib
import os
import time
import cnsl
import netbytes
from cnsl import LogTag
from neterror import FileReadError

FILES_DIR = "files"
HASH_CHUNK_SIZE = 1024 * 1024

def calculate_file_sha256(filepath):
    digest = hashlib.sha256()
    with open(filepath, "rb") as file:
        while True:
            chunk = file.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()

class FileSession:
    def __init__(self, conn, fd, filename, chunk_size, file_size):
        self.conn = conn
        self.fd = fd
        self.filename = filename
        self.chunk_size = chunk_size
        self.file_size = file_size
        self.start_time = time.time()
        conn.has_session = True
        conn.reset_timeout()

    def resume(self):
        raise NotImplementedError

    def conclusion(self, result):
        raise NotImplementedError

class DownloadSession(FileSession):
    def __init__(self, conn, fd, shadow_name, filename, chunk_size, file_size):
        super().__init__(conn, fd, filename, chunk_size, file_size)
        self.shadow_name = shadow_name
        self.start_offset = 0
        self.offset = 0
        self.bytes_left = file_size

    def get_id(self):
        return self.conn.get_addr()[0]

    def finalize_download(self):
        shadow_path = os.path.join(FILES_DIR, self.shadow_name)
        final_path = os.path.join(FILES_DIR, self.filename)
        os.rename(shadow_path, final_path)
        return final_path

    def delete_shadow(self):
        shadow_path = os.path.join(FILES_DIR, self.shadow_name)
        try:
            if os.path.exists(shadow_path):
                os.remove(shadow_path)
        except OSError:
            pass

    def resume(self):
        try:
            if self.bytes_left == 0:
                return False
            need = min(self.chunk_size, self.bytes_left)
            chunk = self.conn.try_r_exact(need)
            if not chunk:
                return True
            self.fd.write(chunk)
            self.fd.flush()
            self.offset += len(chunk)
            self.bytes_left -= len(chunk)
            return self.bytes_left != 0
        except Exception:
            self.start_offset = self.offset
            raise

    def conclusion(self, result):
        if result:
            self.fd.close()
            final_path = self.finalize_download()
            file_hash = calculate_file_sha256(final_path)
            speed = netbytes.calculate_speed(self.start_time, time.time(), self.file_size - self.start_offset)
            result_str = f"Файл {self.filename} успешно загружен. Скорость: {speed}. SHA-256 после приема: {file_hash}"
            cnsl.log(LogTag.SUCCESS, f"{result_str}")
        else:
            result_str = f"Ошибка при загрузке файла."
            cnsl.log(LogTag.ERROR, f"{result_str}")
        return result_str

class UploadSession(FileSession):
    def __init__(self, conn, fd, filename, chunk_size, file_size, bytes_sent, source_hash=None):
        super().__init__(conn, fd, filename, chunk_size, file_size)
        self.bytes_sent = bytes_sent
        self.start_offset = bytes_sent
        self.source_hash = source_hash

    def resume(self):
        if self.bytes_sent < self.file_size:
            chunk = self.fd.read(self.chunk_size)
            if not chunk:
                raise FileReadError
            send_len = self.conn.try_w_data(chunk)
            self.bytes_sent += send_len
            if send_len < self.chunk_size and self.bytes_sent < self.file_size:
                self.fd.seek(self.bytes_sent)
        return self.bytes_sent < self.file_size

    def conclusion(self, result):
        if result:
            self.fd.close()
            speed = netbytes.calculate_speed(self.start_time, time.time(), self.file_size - self.start_offset)
            result_str = f"Файл {self.filename} успешно отправлен. Скорость: {speed}"
            if self.source_hash:
                result_str += f". SHA-256 до отправки: {self.source_hash}"
            cnsl.log(LogTag.SUCCESS, f"{result_str}")
        else:
            result_str = f"Не удалось прочитать данные из файла."
            cnsl.log(LogTag.ERROR, f"{result_str}")
        return result_str
