#!/usr/bin/env python3
"""Synthetic kitty-graphics workload: streams uncompressed RGBA frames.

Mimics terminal-browser's inline path: every frame changes content, so a
mux that fingerprints image data must re-upload the full frame each time.
"""
import base64
import os
import random
import sys
import time

WIDTH = int(os.environ.get("NOISE_W", "800"))
HEIGHT = int(os.environ.get("NOISE_H", "600"))
FPS = float(os.environ.get("NOISE_FPS", "10"))
CHUNK_RAW = 3072  # encodes to 4096 base64 bytes, the kitty spec max


def frame_bytes(seed: int) -> bytes:
    rng = random.Random(seed)
    # Cheap "changing" frame: solid color + a band of random noise so every
    # frame's payload differs without paying full-random generation cost.
    base = bytes((seed * 37) % 256 for _ in range(4))
    solid = base * (WIDTH * HEIGHT)
    noise_rows = 32
    noise = rng.randbytes(WIDTH * noise_rows * 4)
    offset_row = (seed * 13) % (HEIGHT - noise_rows)
    start = offset_row * WIDTH * 4
    return solid[:start] + noise + solid[start + len(noise):]


def emit_frame(seed: int) -> None:
    payload = base64.standard_b64encode(frame_bytes(seed))
    out = sys.stdout.buffer
    out.write(b"\x1b[H")
    pos = 0
    first = True
    while pos < len(payload):
        chunk = payload[pos : pos + 4096]
        pos += len(chunk)
        more = b"1" if pos < len(payload) else b"0"
        if first:
            ctrl = b"a=T,t=d,f=32,i=1,q=2,s=%d,v=%d,m=%s" % (WIDTH, HEIGHT, more)
            first = False
        else:
            ctrl = b"m=%s,q=2" % more
        out.write(b"\x1b_G" + ctrl + b";" + chunk + b"\x1b\\")
    out.flush()


def main() -> None:
    interval = 1.0 / FPS
    seed = 0
    while True:
        started = time.monotonic()
        emit_frame(seed)
        seed += 1
        remaining = interval - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
