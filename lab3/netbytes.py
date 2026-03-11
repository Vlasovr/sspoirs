FACTOR = 1024

class Size:
    BYTE = 1
    KILOBYTE = FACTOR
    MEGABYTE = KILOBYTE * FACTOR
    GIGABYTE = MEGABYTE * FACTOR

class Names:
    BYTE = "Байт"
    KILOBYTE = "КБ"
    MEGABYTE = "МБ"
    GIGABYTE = "ГБ"

units = [
    (Size.GIGABYTE, Names.GIGABYTE),
    (Size.MEGABYTE, Names.MEGABYTE),
    (Size.KILOBYTE, Names.KILOBYTE),
    (Size.BYTE, Names.BYTE)
]

def calculate_speed(start_time, end_time, size):
    transfer_time = end_time - start_time
    speed = size / transfer_time if transfer_time > 0 else 0
    return human_readable_size(speed) + "/с"

def human_readable_size(num_bytes):
    if num_bytes == 0:
        return f"0 {Names.BYTE}"
    for factor, suffix in units:
        if num_bytes >= factor:
            value = num_bytes / factor
            return f"{value:.2f} {suffix}" if factor != 1 else f"{int(value)} {suffix}"