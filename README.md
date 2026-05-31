# ЛР 1-4 по ССПОИРС

Практический набор клиент-серверных лабораторных работ на Python: TCP, UDP,
передача файлов, возобновление после обрыва, неблокирующая обработка клиентов и
параллельные UDP-сессии.

README рассчитан на демонстрацию руками: как настроить сеть, как поднять сервер,
как подключить клиент, какие команды вводить и как быстро понять, почему ничего
не пингуется.

## Содержание

- [Что внутри](#что-внутри)
- [Требования](#требования)
- [Быстрый старт на одной машине](#быстрый-старт-на-одной-машине)
- [Настройка сети для двух машин](#настройка-сети-для-двух-машин)
- [Общие правила запуска](#общие-правила-запуска)
- [Ручные команды клиента](#ручные-команды-клиента)
- [План ручного показа на двух машинах](#план-ручного-показа-на-двух-машинах)
- [ЛР1: TCP](#лр1-tcp)
- [ЛР2: TCP и UDP](#лр2-tcp-и-udp)
- [ЛР3: TCP, select и параллельная работа](#лр3-tcp-select-и-параллельная-работа)
- [ЛР4: UDP и параллельные сессии](#лр4-udp-и-параллельные-сессии)
- [Автопроверка](#автопроверка)
- [Команды для сдачи и диагностики](#команды-для-сдачи-и-диагностики)
- [Типовые проблемы](#типовые-проблемы)

## Что внутри

| Лаба | Транспорт | Сервер | Клиент | Основной смысл |
| --- | --- | --- | --- | --- |
| ЛР1 | TCP | `lab1/server.py` | `lab1/client.py` | Базовый TCP-сервер, команды, загрузка и скачивание файлов |
| ЛР2 | TCP + UDP | `lab2/server.py` | `lab2/client.py` | Один сервер слушает TCP и UDP на одном порту, клиент выбирает протокол |
| ЛР3 | TCP | `lab3/server.py` | `lab3/client.py` | Неблокирующий TCP-сервер через `select`, несколько клиентов во время файловых сессий |
| ЛР4 | UDP | `lab4/server.py` | `lab4/client.py` | UDP-сервер с отдельными сессиями клиентов и файловыми блокировками |

Во всех лабах есть каталог `files`. Туда складываются принятые файлы и оттуда
удобно скачивать файлы обратно.

## Требования

- Python 3.10 или новее. В проекте используются современные type hints.
- Внешние Python-пакеты не нужны, используется стандартная библиотека.
- Для демонстрации на двух машинах обе машины должны быть в одной локальной сети:
  Wi-Fi, роутер, свитч или прямой Ethernet-кабель.
- На macOS/Windows может потребоваться разрешить входящие подключения для Python
  в Firewall.

Проверка Python:

```bash
python3 --version
```

Если версия ниже `3.10`, установи новый Python и в командах ниже замени
`python3` на свой исполняемый файл, например:

```bash
python3.12 scripts/autocheck_demo.py --labs 1,2,3,4
python3.12 server.py 0.0.0.0 50505
python3.12 client.py
```

На Windows:

```powershell
python --version
```

Если Windows вместо версии открывает Microsoft Store или ничего не делает,
отключи App execution aliases для `python.exe` и `python3.exe` в настройках
Windows и установи обычный Python с python.org.

## Быстрый старт на одной машине

Из корня репозитория:

```bash
python3 scripts/autocheck_demo.py --labs 1,2,3,4
```

На Windows:

```powershell
python scripts\autocheck_demo.py --labs 1,2,3,4
```

В локальном режиме автопроверка сама поднимает серверы на свободных портах,
гоняет команды и проверяет хэши файлов.

## Настройка сети для двух машин

Главное правило:

- сервер запускается на машине, где открыт `server.py`;
- клиент подключается к IP машины сервера;
- `127.0.0.1` и `localhost` работают только внутри той же машины;
- `0.0.0.0` можно использовать только на сервере для bind, клиенту этот адрес
  вводить нельзя.

### Вариант 1: обе машины в одной Wi-Fi/LAN сети

На машине сервера узнай локальный IPv4.

macOS:

```bash
ipconfig getifaddr en0
```

Если `en0` не подходит:

```bash
networksetup -listallhardwareports
ifconfig
```

Ищи активный интерфейс со строкой `inet`, например `192.168.1.42`.

Windows:

```powershell
ipconfig
```

Linux:

```bash
ip -4 addr
```

Проверка с клиентской машины:

```bash
ping <SERVER_IP>
```

Windows:

```powershell
ping <SERVER_IP>
```

### Вариант 2: прямой Ethernet-кабель без интернета

Если компьютеры соединены кабелем напрямую, DHCP обычно нет. macOS может показать
`IP самоназначен` и адрес вида `169.254.x.x`. Это не ошибка, но для сдачи и
отладки надежнее поставить статические адреса вручную.

На машине сервера:

```text
IP Address: 192.168.50.1
Subnet Mask: 255.255.255.0
Router/Gateway: пусто
DNS: пусто
```

На машине клиента:

```text
IP Address: 192.168.50.2
Subnet Mask: 255.255.255.0
Router/Gateway: пусто
DNS: пусто
```

macOS:

```text
System Settings -> Network -> USB 10/100/1000 LAN/Ethernet -> Details -> TCP/IP
Configure IPv4: Manually
```

Windows:

```text
Settings -> Network & Internet -> Advanced network settings -> More adapter options
Ethernet -> Properties -> Internet Protocol Version 4 (TCP/IPv4)
Use the following IP address
```

Linux через NetworkManager:

```bash
nm-connection-editor
```

Проверка после настройки:

```bash
ping 192.168.50.1
```

Если пинг не идет:

- проверь, что Ethernet-интерфейс активен;
- проверь, что на обеих машинах маска `255.255.255.0`;
- временно выключи Firewall или Stealth Mode;
- попробуй другой кабель/переходник/порт;
- убедись, что пингуешь IP сервера, а не IP клиента.

### Можно ли использовать 169.254.x.x

Можно, если обе машины получили адреса `169.254.x.x` и маску `255.255.0.0`.
Тогда сервер запускается на своем `169.254.x.x`, а клиент подключается к нему.
Но если есть проблемы с пингом, проще сразу перейти на ручные `192.168.50.1` и
`192.168.50.2`.

## Общие правила запуска

Команды ниже предполагают, что ты находишься в корне репозитория:

```bash
cd /Users/Roman/Documents/Git/sspoirs
```

На сервере можно bind-иться на конкретный IP:

```bash
python3 server.py 192.168.50.1 50505
```

или на все интерфейсы:

```bash
python3 server.py 0.0.0.0 50505
```

Для демонстрации обычно удобнее `0.0.0.0`, но клиенту нужно вводить реальный IP
сервера, например `192.168.50.1`.

Порты по умолчанию:

| Лаба | Рекомендуемый порт |
| --- | --- |
| ЛР1 | `50505` |
| ЛР2 | `50505` |
| ЛР3 | `50500` |
| ЛР4 | `50500` |

Если порт занят, выбери другой, например `50506`, `50600`, `6060`.

## Ручные команды клиента

После запуска `client.py` он спрашивает IP, порт и, где нужно, протокол. Внутри
интерактивного клиента доступны команды:

| Команда | Где работает | Что делает |
| --- | --- | --- |
| `TIME` | ЛР1-ЛР4 | Возвращает время сервера |
| `ECHO <текст>` | ЛР1-ЛР4 | Возвращает текст обратно |
| `UPLOAD "<путь-к-файлу>"` | ЛР1-ЛР4 | Отправляет файл с клиента на сервер |
| `UPLOAD <имя-на-сервере> "<путь-к-файлу>"` | ЛР1-ЛР4 | Отправляет файл и сохраняет на сервере под заданным именем |
| `DOWNLOAD <файл-на-сервере>` | ЛР1-ЛР4 | Скачивает файл с сервера на клиент |
| `DOWNLOAD <имя-на-клиенте> <файл-на-сервере>` | ЛР1-ЛР4 | Скачивает файл и сохраняет на клиенте под заданным именем |
| `CLOSE` | ЛР1, ЛР2 TCP, ЛР3 TCP, ЛР4 UDP | Закрывает текущую сессию |
| `back` | Клиентский UI | Вернуться к вводу IP/порта |
| `quit` | Клиентский UI | Выйти из клиента |

Примеры:

```text
TIME
ECHO hello
UPLOAD "/Users/Roman/Desktop/test.txt"
UPLOAD server_copy.txt "/Users/Roman/Desktop/test with spaces.txt"
DOWNLOAD server_copy.txt
DOWNLOAD local_copy.txt server_copy.txt
CLOSE
```

Пути с пробелами обязательно бери в кавычки. Команда `UPLOAD` получает путь на
клиентской машине. Команда `DOWNLOAD` получает имя или путь файла на серверной
машине.

Если в `DOWNLOAD` указан файл без папки, сервер ищет его в `labN/files`. Если в
`UPLOAD` не указать имя, на сервере будет использовано исходное имя файла.

Принятые файлы сохраняются:

```text
lab1/files
lab2/files
lab3/files
lab4/files
```

Если видишь `Файл с таким названием уже существует`, удали старый файл из
соответствующего `files` или используй новое имя.

## План ручного показа на двух машинах

Ниже готовый сценарий для показа преподавателю. В примерах:

- машина сервера: `192.168.50.1`;
- машина клиента: `192.168.50.2`;
- корень проекта: `/Users/Roman/Documents/Git/sspoirs`;
- `python3` должен быть версии `3.10+`. Если у тебя новый Python называется
  `python3.12`, выставь `PY=python3.12`.

Команды ниже записаны для macOS/Linux. На Windows используй тот же порядок, но
замени `export` на `$env:NAME="value"`, `python3` на `python`, а пути на свои.

### Подготовка перед показом

На обеих машинах:

```bash
export ROOT=/Users/Roman/Documents/Git/sspoirs
export PY=python3
$PY --version
cd "$ROOT"
```

Если вывод ниже `Python 3.10`, замени переменную:

```bash
export PY=python3.12
```

На машине сервера:

```bash
export SERVER_IP=192.168.50.1
export CLIENT_IP=192.168.50.2
ping "$CLIENT_IP"
```

На машине клиента:

```bash
export SERVER_IP=192.168.50.1
ping "$SERVER_IP"
```

Если `ping` не идет, сначала исправь сеть. Лабы не заработают, пока машины не
видят друг друга.

На обеих машинах можно очистить старые демонстрационные файлы:

```bash
find "$ROOT"/lab{1,2,3,4}/files -type f -name 'manual_*' -delete
```

На машине клиента создай файлы для передачи:

```bash
mkdir -p /tmp/sspoirs-demo
$PY - <<'PY'
from pathlib import Path
import os

demo = Path("/tmp/sspoirs-demo")
demo.mkdir(parents=True, exist_ok=True)
(demo / "manual_small.txt").write_text("SSPOIRS manual demo\n", encoding="utf-8")
(demo / "manual_big.bin").write_bytes(os.urandom(64 * 1024 * 1024))
print(demo)
PY
```

Во всех интерактивных клиентах вводи именно IP сервера, например
`192.168.50.1`. Не вводи `0.0.0.0`, `127.0.0.1` или `localhost` на клиентской
машине.

### ЛР1: ручной показ TCP

Машина сервера, терминал 1:

```bash
cd "$ROOT/lab1"
$PY server.py 0.0.0.0 50505
```

Машина сервера, терминал 2 для демонстрации открытого TCP-порта:

```bash
lsof -nP -iTCP:50505 -sTCP:LISTEN
netstat -anv | grep 50505
```

Машина клиента, терминал 1:

```bash
nc -vz "$SERVER_IP" 50505
nmap -Pn -p 50505 "$SERVER_IP"
```

Машина клиента, терминал 2:

```bash
cd "$ROOT/lab1"
$PY client.py
```

Внутри клиента:

```text
192.168.50.1
50505
TIME
ECHO manual lab1 tcp
UPLOAD manual_l1_small.txt "/tmp/sspoirs-demo/manual_small.txt"
DOWNLOAD manual_l1_back.txt manual_l1_small.txt
CLOSE
```

Что показать:

- на сервере видно подключение клиента и команды;
- `TIME` возвращает время сервера;
- `ECHO` возвращает введенный текст;
- файл появляется на сервере в `lab1/files/manual_l1_small.txt`;
- скачанный файл появляется на клиенте в `lab1/files/manual_l1_back.txt`;
- `nmap` показывает `50505/tcp open`.

Проверка файлов после сценария:

```bash
ls -lh "$ROOT/lab1/files"/manual_*
```

### ЛР2: ручной показ TCP и UDP

Машина сервера:

```bash
cd "$ROOT/lab2"
$PY server.py 0.0.0.0 50505
```

Машина клиента, TCP-проход:

```bash
cd "$ROOT/lab2"
$PY client.py
```

Внутри клиента выбери TCP:

```text
192.168.50.1
50505
1
TIME
ECHO manual lab2 tcp
UPLOAD manual_l2_tcp.txt "/tmp/sspoirs-demo/manual_small.txt"
DOWNLOAD manual_l2_tcp_back.txt manual_l2_tcp.txt
CLOSE
```

После `CLOSE` клиент вернется к выбору подключения. Подключись к тому же серверу
еще раз и выбери UDP:

```text
y
2
TIME
ECHO manual lab2 udp
UPLOAD manual_l2_udp.txt "/tmp/sspoirs-demo/manual_small.txt"
DOWNLOAD manual_l2_udp_back.txt manual_l2_udp.txt
back
```

Если клиент заново спрашивает IP и порт, введи:

```text
192.168.50.1
50505
2
```

Что показать:

- один `lab2/server.py` принимает и TCP, и UDP на порту `50505`;
- в TCP-проходе работает `CLOSE`;
- в UDP-проходе работают `TIME`, `ECHO`, `UPLOAD`, `DOWNLOAD`;
- файлы лежат в `lab2/files`.

Проверка на обеих машинах:

```bash
ls -lh "$ROOT/lab2/files"/manual_*
```

### ЛР3: ручной показ TCP, select и параллельного клиента

Машина сервера:

```bash
cd "$ROOT/lab3"
$PY server.py 0.0.0.0 50500
```

Машина клиента, терминал 1 для длинной передачи:

```bash
cd "$ROOT/lab3"
$PY client.py
```

Внутри первого клиента:

```text
192.168.50.1
50500
UPLOAD manual_l3_big.bin "/tmp/sspoirs-demo/manual_big.bin"
```

Пока идет передача, машина клиента, терминал 2:

```bash
cd "$ROOT/lab3"
$PY client.py
```

Внутри второго клиента:

```text
192.168.50.1
50500
TIME
ECHO manual lab3 parallel client
CLOSE
```

После завершения загрузки в первом клиенте скачай файл обратно:

```text
DOWNLOAD manual_l3_back.bin manual_l3_big.bin
CLOSE
```

Если `UPLOAD` заканчивается слишком быстро и ты не успеваешь открыть второго
клиента, создай файл больше:

```bash
$PY - <<'PY'
from pathlib import Path
import os
Path("/tmp/sspoirs-demo/manual_huge.bin").write_bytes(os.urandom(256 * 1024 * 1024))
PY
```

и повтори:

```text
UPLOAD manual_l3_huge.bin "/tmp/sspoirs-demo/manual_huge.bin"
```

Что показать:

- во время большой передачи второй клиент все равно получает ответ на `TIME`;
- сервер не блокируется на одном клиенте;
- после передачи файл можно скачать обратно;
- в `lab3/files` видны принятые файлы.

Проверка:

```bash
ls -lh "$ROOT/lab3/files"/manual_*
```

### ЛР4: ручной показ UDP и параллельных сессий

Машина сервера:

```bash
cd "$ROOT/lab4"
$PY server.py 0.0.0.0 50500
```

Машина клиента, терминал 1:

```bash
cd "$ROOT/lab4"
$PY client.py
```

Внутри первого клиента введи первые две команды и оставь окно открытым:

```text
192.168.50.1
50500
TIME
ECHO manual lab4 client A
```

Машина клиента, терминал 2, параллельно с первым:

```bash
cd "$ROOT/lab4"
$PY client.py
```

Внутри второго клиента:

```text
192.168.50.1
50500
TIME
ECHO manual lab4 client B
```

Теперь вернись в первый клиент, загрузи файл на сервер и оставь сессию открытой:

```text
UPLOAD manual_l4_a.txt "/tmp/sspoirs-demo/manual_small.txt"
```

Во втором клиенте скачай файл, который загрузил первый клиент:

```text
DOWNLOAD manual_l4_b_back.txt manual_l4_a.txt
CLOSE
```

Вернись в первый клиент и заверши:

```text
DOWNLOAD manual_l4_a_back.txt manual_l4_a.txt
CLOSE
```

Что показать:

- сервер пишет, что запускает UDP-сессии клиентов;
- два клиента могут общаться с сервером параллельно;
- файл, загруженный одним клиентом, можно скачать другим;
- `CLOSE` завершает UDP-сессию клиента.

Проверка:

```bash
ls -lh "$ROOT/lab4/files"/manual_*
```

### Финальный контроль после ручного показа

На машине сервера:

```bash
find "$ROOT"/lab{1,2,3,4}/files -maxdepth 1 -type f -name 'manual_*' -print -exec ls -lh {} \;
```

На машине клиента:

```bash
find "$ROOT"/lab{1,2,3,4}/files -maxdepth 1 -type f -name 'manual_*' -print -exec ls -lh {} \;
```

Если нужно показать автоматический отчет после ручной демонстрации, запускай на
клиентской машине только для поднятой сейчас лабы:

```bash
$PY scripts/autocheck_demo.py --labs 1 --host "$SERVER_IP" --port 50505 --external-server
$PY scripts/autocheck_demo.py --labs 3 --host "$SERVER_IP" --port 50500 --external-server
$PY scripts/autocheck_demo.py --labs 4 --host "$SERVER_IP" --port 50500 --external-server
```

Для ЛР2 в удаленном автотесте нужен еще ЛР1 TCP baseline, поэтому для ручного
показа ЛР2 проще использовать интерактивный план выше.

## ЛР1: TCP

ЛР1 поднимает TCP-сервер. Сервер обслуживает одного клиента за раз и после
отключения ждет следующего.

### Сервер

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab1
python3 server.py 0.0.0.0 50505
```

С конкретным IP:

```bash
python3 server.py 192.168.50.1 50505
```

Аргументы:

```text
python3 server.py [host] [port]
```

Значения по умолчанию:

```text
host = 0.0.0.0
port = 50505
```

### Клиент

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab1
python3 client.py
```

Ввод:

```text
Введите IP-адрес сервера: 192.168.50.1
Введите порт сервера: 50505
```

Ручной сценарий:

```text
TIME
ECHO lab1 tcp
UPLOAD lab1_test.bin "/Users/Roman/Desktop/test.bin"
DOWNLOAD lab1_back.bin lab1_test.bin
CLOSE
```

### TCP вручную через netcat

Для простых команд можно подключиться без `client.py`:

```bash
nc 192.168.50.1 50505
```

После подключения сервер присылает `OK`. Дальше можно вводить:

```text
TIME
ECHO hello
CLOSE
```

Файловые команды через `nc` руками не подходят, потому что после `UPLOAD` и
`DOWNLOAD` идет бинарный обмен размерами и чанками. Для файлов используй
`client.py`.

## ЛР2: TCP и UDP

ЛР2 запускает TCP и UDP на одном IP и одном порту. Клиент после ввода IP/порта
спрашивает протокол:

```text
1 - TCP
2 - UDP
```

### Сервер

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab2
python3 server.py 0.0.0.0 50505
```

С конкретным IP:

```bash
python3 server.py 192.168.50.1 50505
```

Аргументы:

```text
python3 server.py [host] [port]
```

Значения по умолчанию:

```text
host = 192.168.100.7
port = 50505
```

Лучше всегда явно передавать IP и порт, чтобы не зависеть от дефолтного IP.

### Клиент

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab2
python3 client.py
```

TCP-сценарий:

```text
Введите IP-адрес сервера: 192.168.50.1
Введите порт сервера: 50505
Выберите протокол подключения: 1
TIME
ECHO lab2 tcp
UPLOAD lab2_tcp.bin "/Users/Roman/Desktop/test.bin"
DOWNLOAD lab2_tcp_back.bin lab2_tcp.bin
CLOSE
```

UDP-сценарий:

```text
Введите IP-адрес сервера: 192.168.50.1
Введите порт сервера: 50505
Выберите протокол подключения: 2
TIME
ECHO lab2 udp
UPLOAD lab2_udp.bin "/Users/Roman/Desktop/test.bin"
DOWNLOAD lab2_udp_back.bin lab2_udp.bin
back
```

`CLOSE` в UDP-режиме ЛР2 вернет сообщение, что команда применима только для TCP.
Для выхода из UDP-сценария используй `back` или `quit`.

## ЛР3: TCP, select и параллельная работа

ЛР3 использует TCP и неблокирующий сервер с `select`. Во время передачи файла
другой клиент может подключиться и выполнить, например, `TIME`.

### Сервер

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab3
python3 server.py 0.0.0.0 50500
```

С конкретным IP:

```bash
python3 server.py 192.168.50.1 50500
```

Аргументы:

```text
python3 server.py [host] [port]
```

Значения по умолчанию:

```text
host = 192.168.100.7
port = 50500
```

Лучше всегда явно передавать IP и порт.

### Клиент

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab3
python3 client.py
```

Ручной сценарий первого клиента:

```text
Введите IP-адрес сервера: 192.168.50.1
Введите порт сервера: 50500
UPLOAD big_lab3.bin "/Users/Roman/Desktop/big_file.bin"
```

Пока первый клиент передает большой файл, на второй машине или во втором терминале:

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab3
python3 client.py
```

и внутри:

```text
Введите IP-адрес сервера: 192.168.50.1
Введите порт сервера: 50500
TIME
ECHO parallel client
```

Скачать файл обратно:

```text
DOWNLOAD lab3_back.bin big_lab3.bin
CLOSE
```

## ЛР4: UDP и параллельные сессии

ЛР4 работает по UDP. Сервер создает отдельные сессии клиентов и умеет
обрабатывать несколько UDP-клиентов параллельно.

### Сервер

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab4
python3 server.py 0.0.0.0 50500
```

С конкретным IP:

```bash
python3 server.py 192.168.50.1 50500
```

Поддерживаются оба формата аргументов:

```bash
python3 server.py 192.168.50.1 50500
python3 server.py host=192.168.50.1 port=50500
python3 server.py port=50500
```

### Клиент

Обычно достаточно:

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab4
python3 client.py
```

Клиент ЛР4 также умеет принимать локальный адрес bind. Это нужно редко, обычно
оставляй порт `0`, чтобы система сама выбрала свободный UDP-порт:

```bash
python3 client.py 0.0.0.0 0
python3 client.py host=0.0.0.0 port=0
python3 client.py port=6060
```

Ручной сценарий:

```text
Введите IP-адрес сервера: 192.168.50.1
Введите порт сервера: 50500
TIME
ECHO lab4 udp
UPLOAD lab4_udp.bin "/Users/Roman/Desktop/test.bin"
DOWNLOAD lab4_udp_back.bin lab4_udp.bin
CLOSE
```

Проверка параллельности: запусти два `lab4/client.py` одновременно и в обоих
быстро вводи `ECHO`, `TIME`, `UPLOAD` или `DOWNLOAD`.

## Автопроверка

### Локально

Все лабы:

```bash
python3 scripts/autocheck_demo.py --labs 1,2,3,4
```

Одна лаба:

```bash
python3 scripts/autocheck_demo.py --labs 1
python3 scripts/autocheck_demo.py --labs 2
python3 scripts/autocheck_demo.py --labs 3
python3 scripts/autocheck_demo.py --labs 4
```

Отчет в JSON:

```bash
python3 scripts/autocheck_demo.py --labs 1,2,3,4 --json ./report.json
```

Полезные опции:

```text
--labs 1,2,4
--host <IP>
--port <PORT>
--lab-ports "1:50505,2:50505,3:50500,4:50500"
--external-server
--lab1-tcp-host <IP>
--lab1-tcp-port <PORT>
--json <path>
```

### Удаленно на второй машине

Для ЛР1:

На сервере:

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab1
python3 server.py 0.0.0.0 50505
```

На клиентской машине:

```bash
python3 scripts/autocheck_demo.py --labs 1 --host 192.168.50.1 --port 50505 --external-server
```

Для ЛР3:

На сервере:

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab3
python3 server.py 0.0.0.0 50500
```

На клиентской машине:

```bash
python3 scripts/autocheck_demo.py --labs 3 --host 192.168.50.1 --port 50500 --external-server
```

Для ЛР4:

На сервере:

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab4
python3 server.py 0.0.0.0 50500
```

На клиентской машине:

```bash
python3 scripts/autocheck_demo.py --labs 4 --host 192.168.50.1 --port 50500 --external-server
```

Для ЛР2 автопроверке нужен UDP-сервер ЛР2 и отдельный TCP baseline от ЛР1.
Запусти на серверной машине два процесса на разных портах.

Терминал 1:

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab1
python3 server.py 0.0.0.0 50506
```

Терминал 2:

```bash
cd /Users/Roman/Documents/Git/sspoirs/lab2
python3 server.py 0.0.0.0 50505
```

На клиентской машине:

```bash
python3 scripts/autocheck_demo.py --labs 2 --host 192.168.50.1 --port 50505 --external-server --lab1-tcp-host 192.168.50.1 --lab1-tcp-port 50506
```

## Команды для сдачи и диагностики

### Проверить доступность TCP-порта

macOS/Linux:

```bash
nc -vz 192.168.50.1 50505
```

Windows PowerShell:

```powershell
Test-NetConnection 192.168.50.1 -Port 50505
```

Для UDP такой простой проверки нет: UDP не устанавливает соединение. Проверяй
через `client.py` или автопроверку.

### nmap для ЛР1

Со второй машины:

```bash
nmap -Pn -p 50505 192.168.50.1
```

Ожидаемо увидеть порт `50505/tcp open`, если сервер ЛР1 запущен и firewall не
блокирует подключение.

### netstat/lsof на сервере

macOS TCP:

```bash
lsof -nP -iTCP:50505 -sTCP:LISTEN
netstat -anv | grep 50505
```

macOS UDP:

```bash
lsof -nP -iUDP:50500
netstat -anv | grep 50500
```

Linux:

```bash
ss -lntup | grep 50505
ss -lnup | grep 50500
```

Windows:

```powershell
netstat -ano | findstr 50505
netstat -ano | findstr 50500
```

### Узнать IP сервера

macOS Wi-Fi:

```bash
ipconfig getifaddr en0
```

macOS все интерфейсы:

```bash
ifconfig
```

Windows:

```powershell
ipconfig
```

Linux:

```bash
ip -4 addr
```

### Проверить маршрут до сервера

```bash
ping 192.168.50.1
```

Если ping не проходит, серверные программы тоже не будут видны, пока не исправлена
сеть или firewall.

## Типовые проблемы

### Клиент не видит сервер

Проверь по порядку:

1. На сервере открыт правильный `server.py` из нужной лабы.
2. Сервер слушает правильный порт.
3. Клиент вводит реальный IP сервера, а не `0.0.0.0` и не `127.0.0.1`.
4. `ping <SERVER_IP>` проходит.
5. Firewall не блокирует Python.
6. На прямом Ethernet обе машины в одной подсети, например `192.168.50.1/24` и
   `192.168.50.2/24`.

### `Address already in use`

Порт занят. Возьми другой порт или найди процесс.

macOS/Linux:

```bash
lsof -nP -iTCP:50505
lsof -nP -iUDP:50500
```

Windows:

```powershell
netstat -ano | findstr 50505
```

### `Connection refused`

IP доступен, но на этом порту нет сервера или firewall отклоняет подключение.
Проверь, что сервер запущен именно на этом порту.

### `Timeout`, `No route to host`, ping не идет

Это уровень сети:

- неправильный IP;
- разные подсети;
- Ethernet не поднялся;
- firewall/stealth mode;
- кабель или переходник не работает.

Для прямого Ethernet поставь вручную:

```text
server: 192.168.50.1 / 255.255.255.0
client: 192.168.50.2 / 255.255.255.0
router: empty
dns: empty
```

### `Файл с таким названием уже существует`

В папке `labN/files` уже есть файл с таким именем. Удали его или задай другое
имя:

```text
UPLOAD new_name.bin "/Users/Roman/Desktop/file.bin"
DOWNLOAD local_new_name.bin server_file.bin
```

### Файл с пробелами в пути

Используй кавычки:

```text
UPLOAD "server copy.bin" "/Users/Roman/Desktop/my file.bin"
```

### Почему `UPLOAD/DOWNLOAD` не работает через `nc`

Текстовая команда только начинает файловый сценарий. Дальше клиент и сервер
обмениваются 8-байтными числами, смещениями и бинарными блоками файла. Поэтому
для файлов используй `client.py` или `scripts/autocheck_demo.py`.

### Как безопасно перезапустить демонстрацию

1. Останови сервер через `Ctrl+C`.
2. При необходимости очисти `labN/files` от старых тестовых файлов.
3. Запусти сервер заново.
4. Запусти клиента заново и введи IP/порт.
