import re

IP_REGEX = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
PORT_RANGE = (1, 65535)

WRONG_IP_MESSAGE = "Неверный формат IP-адреса. Пример: 192.168.1.1"
WRONG_PORT_MESSAGE = f"Порт должен быть числом от {PORT_RANGE[0]} до {PORT_RANGE[1]}"

def is_valid_ip(ip: str) -> bool:
    if not IP_REGEX.match(ip):
        return False
    return all(0 <= int(part) <= 255 for part in ip.split("."))

def is_valid_port(port: str) -> bool:
    if not port.isdigit():
        return False
    port = int(port)
    return PORT_RANGE[0] <= port <= PORT_RANGE[1]

