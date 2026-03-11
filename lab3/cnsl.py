import os
import sys
import shutil
from enum import Enum
import time

CLIENT_TYPE = "CLIENT"
SERVER_TYPE = "SERVER"
LOG_TYPE = SERVER_TYPE


class LogTag(Enum):
    SUCCESS = "[V] SUCCESS"
    PLUS = "[+] NEW"
    MINUS = "[-] DELETE"
    INFO = "[I] INFO"
    ERROR = "[X] ERROR"
    WARNING = "[!] WARNING"

def log_no_time(tag: LogTag, message: str):
    print(f"\r{tag.value:<11} {message}")

def log_time(tag: LogTag, message: str):
    timestamp = time.strftime('%H:%M:%S')
    print(f"\r{timestamp} {tag.value:<11} {message}")

def log(tag: LogTag, message: str):
    if LOG_TYPE == CLIENT_TYPE:
        log_no_time(tag, message)
    else:
        log_time(tag, message)

def print_inline(text):
    if is_terminal_supported():
        clear_line()
        print(f'\r{text}', end='', flush=True)
    else:
        print(text)

def is_terminal_supported():
    return sys.stdout.isatty()

def clear():
    if is_terminal_supported():
        os.system('cls' if os.name == 'nt' else 'clear')

def clear_line():
    if is_terminal_supported():
        width = shutil.get_terminal_size((80, 20)).columns  # 80 — fallback
        print('\r' + ' ' * width + '\r', end='', flush=True)