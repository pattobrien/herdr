#!/usr/bin/env python3
"""Text churn: scrolling output at ~50 lines/sec, like an agent streaming."""
import sys
import time

i = 0
while True:
    sys.stdout.write(("#%07d " % i) * 14 + "\n")
    sys.stdout.flush()
    i += 1
    time.sleep(0.02)
