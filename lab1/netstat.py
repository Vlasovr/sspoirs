import netio

OK = "OK"
CONNECTION_CLOSED = "Соединение с сервером потеряно"

def get_status(conn):
    result = netio.r_line(conn)
    if not result:
        return CONNECTION_CLOSED
    return result

def send_status(conn, status):
    netio.w_line(conn, status)
