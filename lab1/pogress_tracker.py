import threading
import time
import bytes
import cnsl

class ProgressTracker:
    def __init__(self, start_bytes: int = 0):
        self.bytes = start_bytes
        self.stop_flag = False
        self.thread: threading.Thread | None = None

    def start(self, file_size):
        self.stop_flag = False
        self.thread = threading.Thread(
            target=self._print_progress,
            args=(file_size,),
            daemon=True
        )
        self.thread.start()

    def stop(self):
        self.stop_flag = True
        if self.thread:
            self.thread.join()
        cnsl.clear_line()

    def _print_progress(self, total_size, interval=1.5):
        last_progress_time = time.time() - interval
        last_received = self.bytes
        while not self.stop_flag:
            current_time = time.time()
            delta_time = current_time - last_progress_time
            received = self.bytes
            if delta_time >= interval:
                delta_bytes = received - last_received
                progress = int(received * 100 / total_size)
                speed = bytes.calculate_speed(0, delta_time, delta_bytes)
                received_str = bytes.human_readable_size(received)
                total_str = bytes.human_readable_size(total_size)
                cnsl.print_inline(f"Загрузка: {progress}% ({received_str} / {total_str}), скорость: {speed}")
                last_progress_time = current_time
                last_received = received
            time.sleep(interval)
