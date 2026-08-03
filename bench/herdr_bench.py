#!/usr/bin/env python3
"""Headless input-latency / egress benchmark for terminal multiplexers.

Spawns the target (herdr client, tmux, or a bare shell) inside a PTY whose
window size reports real pixel dimensions, answers common terminal queries
(DA1, DSR, XTWINOPS, kitty a=q) so the target believes it is talking to a
kitty-like host, and measures:

  - keypress -> rendered-echo latency (bytes written to PTY master until the
    typed char appears as printable text in the target's stdout stream)
  - egress bytes/sec written by the target to the host terminal
  - (herdr) HERDR_RENDER_PROF windows parsed from herdr-server.log

Modes: raw | tmux | herdr
"""
import argparse
import fcntl
import json
import os
import pty
import re
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

ROWS, COLS = 50, 200
XPIX, YPIX = 2000, 1300
SAFE_MARKERS = "jkwvyzfgbp"  # avoid CSI final letters like m/H/K/A..D

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))


class AnsiTextExtractor:
    """Classifies a byte stream into printable text vs escape sequences."""

    GROUND, ESC, CSI, OSC, STRING, STRING_ESC, OSC_ESC = range(7)

    def __init__(self):
        self.state = self.GROUND
        self.lock = threading.Lock()
        self.text = []  # list of (monotonic_ts, byte)

    def feed(self, data: bytes, ts: float) -> None:
        state = self.state
        emitted = []
        for b in data:
            if state == self.GROUND:
                if b == 0x1B:
                    state = self.ESC
                elif b >= 0x20 and b != 0x7F:
                    emitted.append(b)
            elif state == self.ESC:
                if b == ord("["):
                    state = self.CSI
                elif b == ord("]"):
                    state = self.OSC
                elif b in (ord("P"), ord("_"), ord("^"), ord("X")):
                    state = self.STRING  # DCS/APC/PM/SOS until ST
                elif b == 0x1B:
                    state = self.ESC
                elif 0x20 <= b <= 0x2F:
                    state = self.ESC  # intermediate (charset designation etc.)
                else:
                    state = self.GROUND  # two-byte escape (ESC 7, ESC 8, ...)
            elif state == self.CSI:
                if 0x40 <= b <= 0x7E:
                    state = self.GROUND
            elif state == self.OSC:
                if b == 0x07:
                    state = self.GROUND
                elif b == 0x1B:
                    state = self.OSC_ESC
            elif state == self.OSC_ESC:
                state = self.GROUND if b == ord("\\") else self.OSC
            elif state == self.STRING:
                if b == 0x1B:
                    state = self.STRING_ESC
            elif state == self.STRING_ESC:
                state = self.GROUND if b == ord("\\") else self.STRING
        self.state = state
        if emitted:
            with self.lock:
                self.text.extend((ts, b) for b in emitted)
                del self.text[:-100000]

    def find_after(self, marker: int, after_ts: float):
        with self.lock:
            for ts, b in self.text:
                if ts > after_ts and b == marker:
                    return ts
        return None


QUERY_REPLIES = [
    (re.compile(rb"\x1b\[0?c"), lambda m: b"\x1b[?62;4;22c"),  # DA1
    (re.compile(rb"\x1b\[>0?c"), lambda m: b"\x1b[>1;4000;13c"),  # DA2 (kitty-ish)
    (re.compile(rb"\x1b\[5n"), lambda m: b"\x1b[0n"),  # DSR status
    (re.compile(rb"\x1b\[6n"), lambda m: b"\x1b[1;1R"),  # DSR cursor
    (re.compile(rb"\x1b\[\?u"), lambda m: b"\x1b[?0u"),  # kitty keyboard
    (re.compile(rb"\x1b\[14t"), lambda m: b"\x1b[4;%d;%dt" % (YPIX, XPIX)),
    (re.compile(rb"\x1b\[16t"), lambda m: b"\x1b[6;%d;%dt" % (YPIX // ROWS, XPIX // COLS)),
    (re.compile(rb"\x1b\[18t"), lambda m: b"\x1b[8;%d;%dt" % (ROWS, COLS)),
]
KITTY_QUERY = re.compile(rb"\x1b_G([^;\x1b]*)(?:;[^\x1b]*)?\x1b\\")


class PtyHost:
    """Owns the PTY, the child process, and the reader/responder thread."""

    def __init__(self, argv, env):
        self.master, slave = pty.openpty()
        winsz = struct.pack("HHHH", ROWS, COLS, XPIX, YPIX)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, winsz)
        tiocsctty = getattr(termios, "TIOCSCTTY", 0x20007461)

        def become_session_leader():
            os.setsid()
            fcntl.ioctl(0, tiocsctty, 0)

        self.proc = subprocess.Popen(
            argv,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            preexec_fn=become_session_leader,
            close_fds=True,
        )
        os.close(slave)
        self.extractor = AnsiTextExtractor()
        self.byte_buckets = {}  # int(second) -> byte count
        self.total_bytes = 0
        self.started = time.monotonic()
        self._stop = threading.Event()
        self._tail = b""
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def _respond(self, data: bytes) -> None:
        window = self._tail + data
        consumed = 0  # end of the last matched query; never re-scan past it
        for pattern, reply in QUERY_REPLIES:
            for m in pattern.finditer(window):
                consumed = max(consumed, m.end())
                try:
                    os.write(self.master, reply(m))
                except OSError:
                    return
        for m in KITTY_QUERY.finditer(window):
            consumed = max(consumed, m.end())
            ctrl = m.group(1).decode("ascii", "replace")
            if "a=q" in ctrl or ("a=" not in ctrl and "i=" in ctrl):
                image_id = "0"
                for part in ctrl.split(","):
                    if part.startswith("i="):
                        image_id = part[2:]
                try:
                    os.write(self.master, b"\x1b_Gi=%s;OK\x1b\\" % image_id.encode())
                except OSError:
                    return
        self._tail = window[max(consumed, len(window) - 64):]

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = os.read(self.master, 65536)
            except OSError:
                break
            if not data:
                break
            ts = time.monotonic()
            self.total_bytes += len(data)
            bucket = int(ts - self.started)
            self.byte_buckets[bucket] = self.byte_buckets.get(bucket, 0) + len(data)
            self.extractor.feed(data, ts)
            self._respond(data)

    def write(self, data: bytes) -> None:
        os.write(self.master, data)

    def close(self) -> None:
        self._stop.set()
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        try:
            os.close(self.master)
        except OSError:
            pass


def typing_test(host: PtyHost, count: int, hz: float, label: str):
    latencies = []
    interval = 1.0 / hz
    for i in range(count):
        marker = SAFE_MARKERS[i % len(SAFE_MARKERS)]
        sent = time.monotonic()
        host.write(marker.encode())
        deadline = sent + 2.0
        hit = None
        while time.monotonic() < deadline:
            hit = host.extractor.find_after(ord(marker), sent)
            if hit is not None:
                break
            time.sleep(0.001)
        latencies.append(None if hit is None else round((hit - sent) * 1000.0, 2))
        host.write(b"\x7f")  # backspace, keep the line short
        remaining = interval - (time.monotonic() - sent)
        if remaining > 0:
            time.sleep(remaining)
    ok = [l for l in latencies if l is not None]
    summary = {
        "label": label,
        "sent": count,
        "echoed": len(ok),
        "p50_ms": round(percentile(ok, 50), 2) if ok else None,
        "p95_ms": round(percentile(ok, 95), 2) if ok else None,
        "max_ms": max(ok) if ok else None,
        "raw": latencies,
    }
    return summary


def percentile(values, pct):
    values = sorted(values)
    if not values:
        return float("nan")
    k = (len(values) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def egress_window(host: PtyHost, seconds: float, label: str):
    start_total = host.total_bytes
    start = time.monotonic()
    time.sleep(seconds)
    delta = host.total_bytes - start_total
    return {
        "label": label,
        "seconds": round(time.monotonic() - start, 2),
        "bytes": delta,
        "bytes_per_sec": int(delta / max(time.monotonic() - start, 0.001)),
    }


CHURN_SCRIPT = os.path.join(BENCH_DIR, "churn.py")
CHURN_CMD = f"python3 {CHURN_SCRIPT}"


class HerdrCli:
    def __init__(self, session, env, binary="herdr"):
        self.env = env
        self.session = session
        self.binary = binary

    def run(self, *args, timeout=15):
        proc = subprocess.run(
            [self.binary, *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc


def wait_for(predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {what}")


def bench_herdr(args, results):
    session = args.session
    config = os.path.join(BENCH_DIR, "bench-config.toml")
    server_log = os.path.expanduser(f"~/.config/herdr/sessions/{session}/herdr-server.log")
    if os.path.exists(server_log):
        os.remove(server_log)

    env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR")}
    env.update(
        TERM="xterm-kitty",
        COLORTERM="truecolor",
        HERDR_CONFIG_PATH=config,
        HERDR_RENDER_PROF="1",
        HERDR_LOG="herdr=info",
    )
    bench_socket = os.path.expanduser(f"~/.config/herdr/sessions/{session}/herdr.sock")
    cli_env = dict(env, HERDR_SOCKET_PATH=bench_socket)
    cli = HerdrCli(session, cli_env, binary=args.binary)

    host = PtyHost([args.binary, "--session", session], env)
    try:
        wait_for(
            lambda: cli.run("pane", "list").returncode == 0
            and '"type":"pane_list"' in cli.run("pane", "list").stdout,
            30,
            "herdr session API",
        )
        time.sleep(3)  # let the UI settle
        pane_list = cli.run("pane", "list").stdout
        results["pane_list_initial"] = pane_list
        # Safety guard: a fresh bench session must have exactly one pane and
        # no agent-occupied panes. Anything else means we are NOT talking to
        # the isolated bench session -> abort before mutating anything.
        panes = json.loads(pane_list)["result"]["panes"]
        if len(panes) != 1 or any(p.get("agent") for p in panes):
            raise RuntimeError(
                f"refusing to continue: target session does not look like a "
                f"fresh bench session ({len(panes)} panes)"
            )
        typing_pane = first_pane_id(pane_list)
        cli.run("pane", "run", typing_pane, "zsh", "-f")
        time.sleep(2)

        results["idle_egress"] = egress_window(host, 6, "idle")
        results["typing_idle"] = typing_test(host, 40, 4, "typing_idle")

        split = cli.run("pane", "split", typing_pane, "--direction", "right", "--no-focus")
        results["split_output"] = split.stdout + split.stderr
        time.sleep(2)
        churn_pane = other_pane_id(cli.run("pane", "list").stdout, typing_pane)
        cli.run("pane", "run", churn_pane, "python3", CHURN_SCRIPT)
        time.sleep(2)
        results["churn_egress"] = egress_window(host, 6, "churn_only")
        results["typing_churn"] = typing_test(host, 40, 4, "typing_churn")
        cli.run("pane", "send-keys", churn_pane, "ctrl+c")
        time.sleep(1)

        noise = os.path.join(BENCH_DIR, "kitty_noise.py")
        cli.run("pane", "run", churn_pane, "python3", noise)
        time.sleep(3)
        results["graphics_egress"] = egress_window(host, 6, "graphics_only")
        results["typing_graphics"] = typing_test(host, 40, 4, "typing_graphics")
        cli.run("pane", "send-keys", churn_pane, "ctrl+c")
    finally:
        try:
            cli.run("session", "stop", session, timeout=10)
        except Exception:
            pass
        host.close()
    time.sleep(1)
    results["render_prof"] = parse_render_prof(server_log)
    try:
        cli.run("session", "delete", session, timeout=10)
    except Exception:
        pass


def pane_ids(pane_list: str):
    payload = json.loads(pane_list)
    return [p["pane_id"] for p in payload["result"]["panes"]]


def first_pane_id(pane_list: str) -> str:
    ids = pane_ids(pane_list)
    if not ids:
        raise RuntimeError(f"no pane id found in: {pane_list!r}")
    return ids[0]


def other_pane_id(pane_list: str, not_this: str) -> str:
    for pane_id in pane_ids(pane_list):
        if pane_id != not_this:
            return pane_id
    raise RuntimeError(f"no second pane in: {pane_list!r}")


def parse_render_prof(path: str):
    windows = []
    if not os.path.exists(path):
        return {"error": f"log not found: {path}"}
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            if "render.prof" not in line:
                continue
            entry = {}
            counters = re.search(r'counters=([^ ]*(?: [^=]+=[^ ]*)*?) durations=', line)
            m = re.search(r"counters=(\S*)", line)
            d = re.search(r"durations=(.*?)( render profiler window)?$", line.strip())
            if m:
                entry["counters"] = m.group(1)
            if d:
                entry["durations"] = d.group(1)
            windows.append(entry)
    return windows


def bench_raw(args, results):
    env = dict(os.environ, TERM="xterm-kitty", COLORTERM="truecolor")
    host = PtyHost(["zsh", "-f"], env)
    try:
        time.sleep(2)
        results["idle_egress"] = egress_window(host, 6, "idle")
        results["typing_idle"] = typing_test(host, 40, 4, "typing_idle")
        noise = os.path.join(BENCH_DIR, "kitty_noise.py")
        host.write(b"python3 %s &\n" % noise.encode())
        time.sleep(3)
        results["graphics_egress"] = egress_window(host, 6, "graphics_only")
        results["typing_graphics"] = typing_test(host, 40, 4, "typing_graphics")
        host.write(b"\x03kill %1\n")
    finally:
        host.close()


def bench_tmux(args, results):
    sock = "herdrbench"
    env = dict(os.environ, TERM="xterm-kitty", COLORTERM="truecolor")
    subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True)
    host = PtyHost(
        ["tmux", "-L", sock, "-f", "/dev/null", "new-session", "-s", "bench", "zsh -f"],
        env,
    )

    def tmux(*a):
        return subprocess.run(["tmux", "-L", sock, *a], capture_output=True, text=True)

    try:
        time.sleep(2)
        results["idle_egress"] = egress_window(host, 6, "idle")
        results["typing_idle"] = typing_test(host, 40, 4, "typing_idle")
        tmux("split-window", "-h", "-t", "bench", "sh -c '%s'" % CHURN_CMD.replace("'", "'\\''"))
        tmux("select-pane", "-t", "bench.0")
        time.sleep(2)
        results["churn_egress"] = egress_window(host, 6, "churn_only")
        results["typing_churn"] = typing_test(host, 40, 4, "typing_churn")
        tmux("kill-pane", "-t", "bench.1")
    finally:
        tmux("kill-server")
        host.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["raw", "tmux", "herdr"])
    parser.add_argument(
        "--session", default=f"herdr-bench-{int(time.time()) % 1000000}"
    )
    parser.add_argument("--binary", default="herdr")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    results = {"mode": args.mode, "rows": ROWS, "cols": COLS}
    started = time.time()
    try:
        {"raw": bench_raw, "tmux": bench_tmux, "herdr": bench_herdr}[args.mode](args, results)
    except Exception as exc:  # noqa: BLE001
        results["error"] = f"{type(exc).__name__}: {exc}"
    results["wall_seconds"] = round(time.time() - started, 1)

    out = args.out or os.path.join(BENCH_DIR, f"results-{args.mode}.json")
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2)
    print(json.dumps({k: v for k, v in results.items() if k != "render_prof"}, indent=2, default=str))
    print(f"\nresults written to {out}")


if __name__ == "__main__":
    main()
