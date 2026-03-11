import argparse
import netregex

DEFAULT_IP = "192.168.100.7"
DEFAULT_PORT = 50505


def parse_args():
    parser = argparse.ArgumentParser(description="Сервер для обработки запросов.")
    parser.add_argument('host', type=str, nargs='?',
                        default=DEFAULT_IP, help=f"IP-адрес сервера (по умолчанию {DEFAULT_IP})")
    parser.add_argument('port', type=int, nargs='?',
                        default=DEFAULT_PORT, help=f"Порт сервера (по умолчанию {DEFAULT_PORT})")
    return parser.parse_args()

def get_args():
    args = parse_args()
    if not netregex.is_valid_ip(args.host):
        exit_with_parse_error(netregex.WRONG_IP_MESSAGE)
        exit(1)
    if not netregex.is_valid_port(str(args.port)):
        exit_with_parse_error(netregex.WRONG_PORT_MESSAGE)
    return args.host, args.port

def exit_with_parse_error(message):
    print(message)
    print()
    print("Корректный запуск программы:")
    print("python server.py <IP-адрес> <Порт>")
    print()
    print("Пример:")
    print("python server.py 192.168.1.100 50505")
    exit(1)


