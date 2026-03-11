class ClientDisconnected(Exception):
    pass

class CommandCancel(Exception):
    pass

class ServerError(Exception):
    pass

class ConnectionClosed(Exception):
    pass