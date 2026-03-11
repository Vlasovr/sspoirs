import sys
import cnsl
import netregex

DEFAULT_IP = "192.168.100.7"
DEFAULT_PORT = 50500

def parse_args():
    args = {'host': DEFAULT_IP, 'port': DEFAULT_PORT}

    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', maxsplit=1)
            if key == 'host':
                args['host'] = value
            elif key == 'port':
                try:
                    args['port'] = int(value)
                except ValueError:
                    exit_with_parse_error("Порт должен быть числом.")
            else:
                exit_with_parse_error(f"Неизвестный аргумент: {key}")
        else:
            if args['host'] == DEFAULT_IP:
                args['host'] = arg
            elif args['port'] == DEFAULT_PORT:
                try:
                    args['port'] = int(arg)
                except ValueError:
                    exit_with_parse_error("Порт должен быть числом.")
            else:
                exit_with_parse_error(f"Лишний аргумент: {arg}")

    return args['host'], args['port']

def get_args():
    host, port = parse_args()

    if not netregex.is_valid_ip(host):
        exit_with_parse_error(netregex.WRONG_IP_MESSAGE)

    if not netregex.is_valid_port(str(port)):
        exit_with_parse_error(netregex.WRONG_PORT_MESSAGE)

    return host, port

def exit_with_parse_error(message):
    filename = "server.py" if cnsl.LOG_TYPE == cnsl.SERVER_TYPE else "client.py"

    print(message)
    print()
    print("Корректный запуск программы:")
    print(f"python {filename} <IP-адрес> <Порт>")
    print(f"python {filename} host=192.168.1.100 port=50505")
    print()
    print("Примеры:")
    print(f"python {filename}")
    print(f"python {filename} 192.168.1.100 50505")
    print(f"python {filename} port=6060")
    exit(1)
