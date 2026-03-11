#!/usr/bin/env python3
import argparse
import hashlib
import importlib
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALHOST = "127.0.0.1"
LOCAL_BIND_HOST = "0.0.0.0"
DEFAULT_REMOTE_PORTS = {
    "lab1": 50505,
    "lab2": 50505,
    "lab3": 50500,
    "lab4": 50500,
}


@dataclass
class CheckResult:
    lab: str
    ok: bool
    details: dict
    error: str | None = None


class ServerProcess:
    def __init__(self, lab_dir: Path, host: str, port: int):
        self.lab_dir = lab_dir
        self.host = host
        self.port = port
        self.proc = None
        self.logs = []
        self._log_thread = None

    def start(self):
        cmd = [sys.executable, "-u", "server.py", self.host, str(self.port)]
        self.proc = subprocess.Popen(
            cmd,
            cwd=self.lab_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._log_thread = threading.Thread(target=self._drain_logs, daemon=True)
        self._log_thread.start()

        deadline = time.time() + 5
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early: {' | '.join(self.tail_logs(20))}")
            if self.logs and any("Сервер запущен" in line for line in self.logs[-5:]):
                return
            time.sleep(0.05)

        # fallback readiness
        time.sleep(0.3)
        if self.proc.poll() is not None:
            raise RuntimeError(f"server not ready: {' | '.join(self.tail_logs(20))}")

    def stop(self):
        if not self.proc:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)

    def tail_logs(self, n=30):
        return self.logs[-n:]

    def _drain_logs(self):
        if not self.proc or not self.proc.stdout:
            return
        for line in self.proc.stdout:
            self.logs.append(line.strip())


def find_free_port(require_udp=False, bind_host=LOCALHOST):
    while True:
        port = random.randint(40000, 55000)
        tcp_ok = False
        udp_ok = not require_udp

        ts = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            ts.bind((bind_host, port))
            tcp_ok = True
        except OSError:
            tcp_ok = False
        finally:
            ts.close()

        if require_udp:
            us = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                us.bind((bind_host, port))
                udp_ok = True
            except OSError:
                udp_ok = False
            finally:
                us.close()

        if tcp_ok and udp_ok:
            return port


def unique_name(prefix):
    token = uuid.uuid4().hex[:10]
    return f"{prefix}_{token}.bin"


def random_payload(size):
    return os.urandom(size)


def md5(data):
    return hashlib.md5(data).hexdigest()


def format_speed(byte_count, duration):
    if duration <= 0:
        return "0 B/s"
    speed = byte_count / duration
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    idx = 0
    while speed >= 1024 and idx < len(units) - 1:
        speed /= 1024
        idx += 1
    return f"{speed:.2f} {units[idx]}"


class TcpSession:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = b""

    @classmethod
    def connect(cls, host, port, timeout=10):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        return cls(sock)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def write_line(self, text):
        self.sock.sendall((text + "\n").encode())

    def write_u64(self, value):
        self.sock.sendall(int(value).to_bytes(8, "big"))

    def write_bytes(self, data):
        self.sock.sendall(data)

    def read_exact(self, n):
        out = bytearray()
        if self.buf:
            take = min(len(self.buf), n)
            out += self.buf[:take]
            self.buf = self.buf[take:]
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise EOFError("connection closed")
            out += chunk
        return bytes(out)

    def read_u64(self):
        return int.from_bytes(self.read_exact(8), "big")

    def readline(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise EOFError("connection closed")
            self.buf += chunk
        line, _, rest = self.buf.partition(b"\n")
        self.buf = rest
        return line.decode(errors="ignore").strip()


def expect_status(session: TcpSession, expected="OK"):
    status = session.readline()
    if status != expected:
        raise AssertionError(f"expected status={expected}, got={status}")
    return status


def tcp_upload_status_before(session: TcpSession, filename: str, payload: bytes, stop_after=None):
    session.write_line(f"UPLOAD {filename}")
    status = session.readline()
    if status != "OK":
        raise AssertionError(f"UPLOAD rejected: {status}")
    _chunk_size = session.read_u64()
    session.write_u64(len(payload))
    offset = session.read_u64()

    target = len(payload) if stop_after is None else stop_after
    if target < offset:
        target = offset

    if target > offset:
        session.write_bytes(payload[offset:target])

    if stop_after is not None:
        return {"offset": offset, "sent": target}

    response = session.readline()
    return {"offset": offset, "response": response}


def tcp_download_status_before(session: TcpSession, filename: str):
    session.write_line(f"DOWNLOAD {filename}")
    status = session.readline()
    if status != "OK":
        raise AssertionError(f"DOWNLOAD rejected: {status}")

    session.write_u64(64 * 1024)
    file_size = session.read_u64()
    session.write_u64(0)

    t0 = time.time()
    data = session.read_exact(file_size)
    dt = time.time() - t0
    response = session.readline()
    return data, response, dt


def tcp_upload_status_after(session: TcpSession, filename: str, payload: bytes, throttle=0.0):
    session.write_line(f"UPLOAD {filename}")
    status = session.readline()
    if status != "OK":
        raise AssertionError(f"UPLOAD rejected: {status}")

    _chunk_size = session.read_u64()
    session.write_u64(len(payload))
    offset = session.read_u64()

    pos = offset
    step = 64 * 1024
    t0 = time.time()
    while pos < len(payload):
        nxt = min(pos + step, len(payload))
        session.write_bytes(payload[pos:nxt])
        pos = nxt
        if throttle > 0:
            time.sleep(throttle)

    response = session.readline()
    ready = session.readline()
    if ready != "OK":
        raise AssertionError(f"missing ready status after upload: {ready}")
    return response, time.time() - t0


def tcp_download_status_after(session: TcpSession, filename: str):
    session.write_line(f"DOWNLOAD {filename}")
    status = session.readline()
    if status != "OK":
        raise AssertionError(f"DOWNLOAD rejected: {status}")

    session.write_u64(64 * 1024)
    file_size = session.read_u64()
    session.write_u64(0)

    t0 = time.time()
    data = session.read_exact(file_size)
    dt = time.time() - t0

    response = session.readline()
    ready = session.readline()
    if ready != "OK":
        raise AssertionError(f"missing ready status after download: {ready}")
    return data, response, dt


def load_netio_module(lab_dir: Path):
    for name in ["netio", "netbytes"]:
        sys.modules.pop(name, None)

    sys.path.insert(0, str(lab_dir))
    try:
        return importlib.import_module("netio")
    finally:
        sys.path.pop(0)


class UdpClient:
    def __init__(self, netio, host, port, timeout=30):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((LOCAL_BIND_HOST, 0))
        self.sock.settimeout(0.1)
        self.conn = netio.UdpConnection(self.sock, (host, port), timeout=timeout)
        self.conn.message_timeout = 3

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def udp_upload(client: UdpClient, filename: str, payload: bytes, stop_after=None):
    conn = client.conn
    conn.send_command(f"UPLOAD {filename}")
    status = conn.get_status()
    if status != "OK":
        raise AssertionError(f"UPLOAD rejected: {status}")

    chunk_size = conn.r_long()
    conn.w_long(len(payload))
    offset = conn.r_long()

    target = len(payload) if stop_after is None else stop_after
    if target < offset:
        target = offset

    t0 = time.time()
    pos = offset
    while pos < target:
        nxt = min(pos + chunk_size, target)
        conn.w_data(payload[pos:nxt])
        pos = nxt

    if stop_after is not None:
        return {"offset": offset, "sent": target}

    response = conn.r_line()
    return {"offset": offset, "response": response, "duration": time.time() - t0}


def udp_download(client: UdpClient, filename: str):
    conn = client.conn
    conn.send_command(f"DOWNLOAD {filename}")
    status = conn.get_status()
    if status != "OK":
        raise AssertionError(f"DOWNLOAD rejected: {status}")

    chunk_size = 64 * 1024
    conn.w_long(chunk_size)
    file_size = conn.r_long()
    conn.w_long(0)

    t0 = time.time()
    data = bytearray()
    while len(data) < file_size:
        need = min(chunk_size, file_size - len(data))
        data.extend(conn.r_exact(need))
    dt = time.time() - t0
    response = conn.r_line()
    return bytes(data), response, dt


def cleanup_lab_file(lab_dir: Path, filename: str):
    file_path = lab_dir / "files" / filename
    if file_path.exists():
        file_path.unlink()


def check_lab1(host, port, manage_server=True):
    lab_dir = ROOT / "lab1"
    server = ServerProcess(lab_dir, host, port) if manage_server else None
    payload = random_payload(2 * 1024 * 1024)
    fname = unique_name("autocheck_l1")

    try:
        if manage_server:
            cleanup_lab_file(lab_dir, fname)
            server.start()

        c1 = TcpSession.connect(host, port)
        expect_status(c1)

        c1.write_line("TIME")
        time_resp = c1.readline()
        expect_status(c1)

        msg = "hello_lab1"
        c1.write_line(f"ECHO {msg}")
        echo_resp = c1.readline()
        expect_status(c1)

        cut = len(payload) // 3
        tcp_upload_status_before(c1, fname, payload, stop_after=cut)
        c1.close()

        c1b = TcpSession.connect(host, port)
        expect_status(c1b)

        t_up = time.time()
        resume = tcp_upload_status_before(c1b, fname, payload)
        up_dt = time.time() - t_up
        expect_status(c1b)

        t_down = time.time()
        downloaded, down_resp, down_dt = tcp_download_status_before(c1b, fname)
        expect_status(c1b)
        c1b.close()

        c2 = TcpSession.connect(host, port)
        expect_status(c2)
        c2.write_line("TIME")
        second_client_time = c2.readline()
        expect_status(c2)

        c2.close()

        if echo_resp != msg:
            raise AssertionError("echo mismatch")
        if md5(downloaded) != md5(payload):
            raise AssertionError("downloaded file hash mismatch")
        if "успешно" not in resume["response"].lower():
            raise AssertionError(f"unexpected upload response: {resume['response']}")
        if "успешно" not in down_resp.lower():
            raise AssertionError(f"unexpected download response: {down_resp}")
        if not second_client_time:
            raise AssertionError("second client TIME response is empty")
        if resume["offset"] <= 0:
            raise AssertionError("resume offset was not detected")

        return CheckResult(
            lab="lab1",
            ok=True,
            details={
                "host": host,
                "port": port,
                "resume_offset": resume["offset"],
                "time_response": time_resp,
                "upload_speed": format_speed(len(payload) - resume["offset"], up_dt),
                "download_speed": format_speed(len(payload), down_dt),
                "upload_response": resume["response"],
                "download_response": down_resp,
            },
        )

    except Exception as e:
        details = {"host": host, "port": port}
        if server:
            details["logs"] = server.tail_logs(30)
        return CheckResult("lab1", False, details, str(e))
    finally:
        if server:
            server.stop()
        if manage_server:
            cleanup_lab_file(lab_dir, fname)


def check_lab2(host, port, manage_server=True):
    lab_dir = ROOT / "lab2"
    server = ServerProcess(lab_dir, host, port) if manage_server else None
    payload = random_payload(4 * 1024 * 1024)
    fname_tcp = unique_name("autocheck_l2_tcp")
    fname_udp = unique_name("autocheck_l2_udp")

    try:
        if manage_server:
            cleanup_lab_file(lab_dir, fname_tcp)
            cleanup_lab_file(lab_dir, fname_udp)
            server.start()

        # TCP baseline
        c = TcpSession.connect(host, port)
        expect_status(c)

        t0 = time.time()
        tcp_up = tcp_upload_status_before(c, fname_tcp, payload)
        tcp_up_dt = time.time() - t0
        expect_status(c)

        t0 = time.time()
        tcp_data, tcp_down_resp, tcp_down_dt = tcp_download_status_before(c, fname_tcp)
        expect_status(c)
        c.close()

        if md5(tcp_data) != md5(payload):
            raise AssertionError("lab2 tcp hash mismatch")

        # UDP path
        netio = load_netio_module(lab_dir)
        u = UdpClient(netio, host, port, timeout=15)

        u.conn.send_command("TIME")
        udp_time = u.conn.r_line()

        udp_up = udp_upload(u, fname_udp, payload)
        udp_data, udp_down_resp, udp_down_dt = udp_download(u, fname_udp)
        u.close()

        if md5(udp_data) != md5(payload):
            raise AssertionError("lab2 udp hash mismatch")

        tcp_total_speed = len(payload) / max(tcp_down_dt, 1e-6)
        udp_total_speed = len(payload) / max(udp_down_dt, 1e-6)
        ratio = udp_total_speed / max(tcp_total_speed, 1e-6)

        return CheckResult(
            lab="lab2",
            ok=True,
            details={
                "host": host,
                "port": port,
                "tcp_upload_response": tcp_up["response"],
                "tcp_download_response": tcp_down_resp,
                "udp_upload_response": udp_up["response"],
                "udp_download_response": udp_down_resp,
                "udp_time_response": udp_time,
                "tcp_download_speed": format_speed(len(payload), tcp_down_dt),
                "udp_download_speed": format_speed(len(payload), udp_down_dt),
                "udp_vs_tcp_ratio": round(ratio, 2),
                "tcp_upload_speed": format_speed(len(payload), tcp_up_dt),
                "udp_upload_speed": format_speed(len(payload), udp_up["duration"]),
            },
        )

    except Exception as e:
        details = {"host": host, "port": port}
        if server:
            details["logs"] = server.tail_logs(30)
        return CheckResult("lab2", False, details, str(e))
    finally:
        if server:
            server.stop()
        if manage_server:
            cleanup_lab_file(lab_dir, fname_tcp)
            cleanup_lab_file(lab_dir, fname_udp)


def check_lab3(host, port, manage_server=True):
    lab_dir = ROOT / "lab3"
    server = ServerProcess(lab_dir, host, port) if manage_server else None
    payload = random_payload(12 * 1024 * 1024)
    fname = unique_name("autocheck_l3")

    try:
        if manage_server:
            cleanup_lab_file(lab_dir, fname)
            server.start()

        upload_result = {}

        def upload_worker():
            s = TcpSession.connect(host, port)
            try:
                expect_status(s)
                response, dt = tcp_upload_status_after(s, fname, payload, throttle=0.0015)
                upload_result["response"] = response
                upload_result["duration"] = dt
            finally:
                s.close()

        th = threading.Thread(target=upload_worker)
        th.start()
        time.sleep(0.2)

        observer = TcpSession.connect(host, port)
        expect_status(observer)
        t0 = time.time()
        observer.write_line("TIME")
        observer_time = observer.readline()
        latency = time.time() - t0
        expect_status(observer)
        observer.close()

        th.join(timeout=120)
        if th.is_alive():
            raise AssertionError("upload worker did not finish")

        d = TcpSession.connect(host, port)
        expect_status(d)
        downloaded, down_resp, down_dt = tcp_download_status_after(d, fname)
        d.close()

        if md5(downloaded) != md5(payload):
            raise AssertionError("lab3 hash mismatch")
        if "успешно" not in upload_result.get("response", "").lower():
            raise AssertionError(f"unexpected upload response: {upload_result.get('response')}")
        if "успешно" not in down_resp.lower():
            raise AssertionError(f"unexpected download response: {down_resp}")

        return CheckResult(
            lab="lab3",
            ok=True,
            details={
                "host": host,
                "port": port,
                "observer_latency_sec": round(latency, 3),
                "observer_time_response": observer_time,
                "upload_speed": format_speed(len(payload), upload_result["duration"]),
                "download_speed": format_speed(len(payload), down_dt),
                "upload_response": upload_result["response"],
                "download_response": down_resp,
            },
        )

    except Exception as e:
        details = {"host": host, "port": port}
        if server:
            details["logs"] = server.tail_logs(30)
        return CheckResult("lab3", False, details, str(e))
    finally:
        if server:
            server.stop()
        if manage_server:
            cleanup_lab_file(lab_dir, fname)


def check_lab4(host, port, manage_server=True):
    lab_dir = ROOT / "lab4"
    server = ServerProcess(lab_dir, host, port) if manage_server else None
    payload = random_payload(2 * 1024 * 1024)
    fname = unique_name("autocheck_l4")

    try:
        if manage_server:
            cleanup_lab_file(lab_dir, fname)
            server.start()
        netio = load_netio_module(lab_dir)

        # parallel echo sessions (2+ clients)
        parallel_errors = []

        def echo_worker(tag):
            try:
                c = UdpClient(netio, host, port, timeout=10)
                for i in range(15):
                    msg = f"{tag}_{i}"
                    c.conn.send_command(f"ECHO {msg}")
                    resp = c.conn.r_line()
                    if resp != msg:
                        raise AssertionError(f"echo mismatch for {tag}: {resp} != {msg}")
                c.close()
            except Exception as e:
                parallel_errors.append(str(e))

        t1 = threading.Thread(target=echo_worker, args=("A",))
        t2 = threading.Thread(target=echo_worker, args=("B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        if parallel_errors:
            raise AssertionError("; ".join(parallel_errors))

        # interrupted upload + resume
        c1 = UdpClient(netio, host, port, timeout=20)
        cut = len(payload) // 3
        udp_upload(c1, fname, payload, stop_after=cut)
        c1.close()

        # Wait until the first session is marked as interrupted and saved by server.
        time.sleep(3.5)

        c1r = UdpClient(netio, host, port, timeout=20)
        c2 = UdpClient(netio, host, port, timeout=20)

        up_info = {}

        def resume_upload():
            info = udp_upload(c1r, fname, payload)
            up_info.update(info)

        upload_thread = threading.Thread(target=resume_upload)
        upload_thread.start()
        time.sleep(0.1)

        t0 = time.time()
        c2.conn.send_command("TIME")
        time_resp = c2.conn.r_line()
        time_latency = time.time() - t0

        upload_thread.join(timeout=120)
        if upload_thread.is_alive():
            raise AssertionError("resume upload did not finish")

        downloaded, down_resp, down_dt = udp_download(c2, fname)

        c1r.close()
        c2.close()

        if md5(downloaded) != md5(payload):
            raise AssertionError("lab4 hash mismatch")
        if "успешно" not in up_info.get("response", "").lower():
            raise AssertionError(f"unexpected upload response: {up_info.get('response')}")
        if "успешно" not in down_resp.lower():
            raise AssertionError(f"unexpected download response: {down_resp}")
        if up_info.get("offset", 0) <= 0:
            raise AssertionError("resume offset was not detected for UDP")

        return CheckResult(
            lab="lab4",
            ok=True,
            details={
                "host": host,
                "port": port,
                "resume_offset": up_info["offset"],
                "upload_response": up_info["response"],
                "download_response": down_resp,
                "download_speed": format_speed(len(payload), down_dt),
                "parallel_time_latency_sec": round(time_latency, 3),
                "parallel_time_response": time_resp,
            },
        )

    except Exception as e:
        details = {"host": host, "port": port}
        if server:
            details["logs"] = server.tail_logs(30)
        return CheckResult("lab4", False, details, str(e))
    finally:
        if server:
            server.stop()
        if manage_server:
            cleanup_lab_file(lab_dir, fname)


def is_local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def parse_lab_ports(raw: str):
    if not raw:
        return {}

    mapping = {}
    items = [item.strip() for item in raw.split(",") if item.strip()]
    for item in items:
        if ":" not in item:
            raise ValueError(f"bad lab port mapping: {item}. Use format 1:50505,2:50505")
        lab_part, port_part = item.split(":", maxsplit=1)
        lab_part = lab_part.strip().lower()
        if lab_part.startswith("lab"):
            lab = lab_part
        elif lab_part.isdigit():
            lab = f"lab{lab_part}"
        else:
            raise ValueError(f"bad lab key in mapping: {lab_part}")
        if lab not in {"lab1", "lab2", "lab3", "lab4"}:
            raise ValueError(f"unsupported lab in mapping: {lab}")
        try:
            port = int(port_part.strip())
        except ValueError as e:
            raise ValueError(f"bad port in mapping: {item}") from e
        if not (1 <= port <= 65535):
            raise ValueError(f"port out of range in mapping: {item}")
        mapping[lab] = port
    return mapping


def resolve_ports(selected_labs, host, manage_server, global_port=None, mapped_ports=None):
    mapped_ports = mapped_ports or {}
    lab_port_map = {}

    if global_port is not None and not (1 <= global_port <= 65535):
        raise ValueError("port must be in range 1..65535")

    if manage_server and global_port is not None and len(selected_labs) > 1 and not mapped_ports:
        raise ValueError("single --port with multiple labs in local mode is ambiguous; use --lab-ports")

    for lab in selected_labs:
        if lab in mapped_ports:
            lab_port_map[lab] = mapped_ports[lab]
            continue
        if global_port is not None:
            lab_port_map[lab] = global_port
            continue
        if manage_server:
            need_udp = lab in {"lab2", "lab4"}
            lab_port_map[lab] = find_free_port(require_udp=need_udp, bind_host=host)
        else:
            lab_port_map[lab] = DEFAULT_REMOTE_PORTS[lab]

    return lab_port_map


def run_checks(selected_labs, host, manage_server, global_port=None, mapped_ports=None):
    checks = []
    lab_port_map = resolve_ports(selected_labs, host, manage_server, global_port=global_port, mapped_ports=mapped_ports)

    if "lab1" in selected_labs:
        checks.append(check_lab1(host, lab_port_map["lab1"], manage_server=manage_server))
    if "lab2" in selected_labs:
        checks.append(check_lab2(host, lab_port_map["lab2"], manage_server=manage_server))
    if "lab3" in selected_labs:
        checks.append(check_lab3(host, lab_port_map["lab3"], manage_server=manage_server))
    if "lab4" in selected_labs:
        checks.append(check_lab4(host, lab_port_map["lab4"], manage_server=manage_server))

    return checks


def print_summary(results):
    print("=" * 72)
    print("AUTOCHECK SUMMARY")
    print("=" * 72)
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        print(f"[{status}] {r.lab}")
        if r.ok:
            for k, v in r.details.items():
                print(f"  - {k}: {v}")
        else:
            print(f"  - error: {r.error}")
            if r.details.get("logs"):
                print("  - server tail:")
                for line in r.details["logs"][-12:]:
                    print(f"      {line}")
        print("-" * 72)


def main():
    parser = argparse.ArgumentParser(description="Autocheck demo for labs 1-4.")
    parser.add_argument(
        "--labs",
        default="1,2,3,4",
        help="Comma-separated labs to run. Example: 1,2,4",
    )
    parser.add_argument(
        "--host",
        default=LOCALHOST,
        help="Server host. Non-local host switches to external mode (no local server start).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Single port for selected labs.",
    )
    parser.add_argument(
        "--lab-ports",
        default="",
        help="Per-lab port map, e.g. 1:50505,2:50505,3:50500,4:50500",
    )
    parser.add_argument(
        "--external-server",
        action="store_true",
        help="Do not start local servers; connect to already running server(s).",
    )
    parser.add_argument("--json", default="", help="Optional path to write JSON report.")
    args = parser.parse_args()

    requested = {f"lab{part.strip()}" for part in args.labs.split(",") if part.strip()}
    allowed = {"lab1", "lab2", "lab3", "lab4"}
    selected = [lab for lab in ["lab1", "lab2", "lab3", "lab4"] if lab in requested and lab in allowed]

    if not selected:
        print("No valid labs selected.")
        return 2

    host = args.host.strip()
    manage_server = not args.external_server and is_local_host(host)

    try:
        mapped_ports = parse_lab_ports(args.lab_ports)
        results = run_checks(
            selected,
            host=host,
            manage_server=manage_server,
            global_port=args.port,
            mapped_ports=mapped_ports,
        )
    except ValueError as e:
        print(f"Argument error: {e}")
        return 2

    mode = "local (auto-start server)" if manage_server else "external (connect only)"
    print(f"Target: {host} | mode: {mode}")
    print_summary(results)

    if args.json:
        data = [
            {
                "lab": r.lab,
                "ok": r.ok,
                "details": r.details,
                "error": r.error,
            }
            for r in results
        ]
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report written to: {out_path}")

    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
