# ЛР 1–4 (ССПОИРС): как запускать и показывать сдачу

## 1. Минимальные требования по демонстрации

- Сдача делается на **2+ реальных машинах в одной сети**.
- VM/UTM допустимы только при отдельном согласовании с преподавателем.
- Для ЛР1 дополнительно показать:
  - `nmap` со второй машины (скан порта сервера),
  - `netstat` на машине сервера (открытые сокеты/порты).

## 2. Быстрая локальная самопроверка (одна машина)

```bash
python3 scripts/autocheck_demo.py --labs 1,2,3,4
```

В этом режиме скрипт сам поднимает локальные `server.py` для каждой лабы.

Если проверяешь на Windows, используй установленный интерпретатор Python:

```powershell
python scripts\autocheck_demo.py --labs 1,2,3,4
```

## 3. Демонстрация на 2 машинах (сервер + партнер)

### На машине сервера

Запускай нужную лабу (пример):

```bash
cd lab1 && python3 server.py 0.0.0.0 50505
```

Для остальных лаб:

```bash
cd lab2 && python3 server.py 0.0.0.0 50505
cd lab3 && python3 server.py 0.0.0.0 50500
cd lab4 && python3 server.py 0.0.0.0 50500
```

`0.0.0.0` здесь используется только для bind на сервере.
Клиенту и `autocheck_demo.py` нужно передавать реальный IP машины сервера в локальной сети, например `192.168.68.112`.

Если сервер запущен на macOS, IP можно узнать так:

```bash
ipconfig getifaddr en0
```

Если `en0` не подходит, смотри адрес через:

```bash
ifconfig | grep "inet "
```

### На машине партнера (клиент/проверка, macOS/Linux)

Запуск автопроверки на удалённый сервер:

```bash
python3 scripts/autocheck_demo.py --labs 1 --host <SERVER_IP> --port 50505
python3 scripts/autocheck_demo.py --labs 2 --host <SERVER_IP> --port 50505
python3 scripts/autocheck_demo.py --labs 3 --host <SERVER_IP> --port 50500
python3 scripts/autocheck_demo.py --labs 4 --host <SERVER_IP> --port 50500
```

Можно не указывать `--port`, тогда будут использованы дефолты:
- `lab1/lab2` → `50505`
- `lab3/lab4` → `50500`

### На машине партнера (клиент/проверка, Windows PowerShell)

Сначала проверь, что порт сервера доступен:

```powershell
Test-NetConnection <SERVER_IP> -Port 50505
```

Если `TcpTestSucceeded : True`, запускай:

```powershell
cd D:\git\sspoirs
python scripts\autocheck_demo.py --labs 1 --host <SERVER_IP> --port 50505
python scripts\autocheck_demo.py --labs 2 --host <SERVER_IP> --port 50505
python scripts\autocheck_demo.py --labs 3 --host <SERVER_IP> --port 50500
python scripts\autocheck_demo.py --labs 4 --host <SERVER_IP> --port 50500
```

Важно:
- не используй `0.0.0.0` в `--host` на машине клиента;
- не запускай `autocheck_demo.py`, пока на машине сервера не поднят соответствующий `server.py`;
- если на Windows команда `python3 ...` печатает только `Python` и ничего не делает, у тебя срабатывает alias из Microsoft Store, а не реальный интерпретатор.

Чтобы проверить это на Windows:

```powershell
Get-Command python
Get-Command python3
where.exe python
where.exe python3
python --version
```

Если путь ведёт в `C:\Users\<user>\AppData\Local\Microsoft\WindowsApps\...`, установи нормальный Python и отключи App execution aliases для `python.exe` и `python3.exe`.

## 4. Полезные опции `autocheck_demo.py`

- `--host <IP>`: адрес удалённого сервера.  
  Если `host` не локальный, скрипт работает в режиме **connect-only** (не стартует локальный сервер).
- `--port <N>`: единый порт для выбранных лаб.
- `--lab-ports "1:50505,2:50505,3:50500,4:50500"`: порты по лабам.
- `--external-server`: принудительно не поднимать локальные серверы.
- `--json <path>`: сохранить отчёт в JSON.

## 5. Пример для отчёта

```bash
python3 scripts/autocheck_demo.py --labs 1,2,3,4 --json ./report.json
```

Если запуск удалённый, обычно удобнее запускать по одной лабе (один поднятый сервер за раз).
