class ClientDisconnected(Exception):
    pass

class CommandCancel(Exception):
    pass

class ServerError(Exception):
    pass

class ConnectionClosed(Exception):
    pass

class FileError(Exception):
    pass

class FileReadError(FileError):
    pass

class NoDataError(FileError):
    pass