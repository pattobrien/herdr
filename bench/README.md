# Input-latency benchmark harness

Headless PTY harness measuring keystroke-to-echo latency and host-bound
egress for herdr, tmux, and a bare shell. Written to diagnose second-long
typing lag while a kitty-graphics pane (terminal browser) streams frames.

## Usage

```sh
python3 bench/herdr_bench.py raw                 # bare zsh floor
python3 bench/herdr_bench.py tmux                # tmux control
python3 bench/herdr_bench.py herdr               # installed herdr binary
python3 bench/herdr_bench.py herdr \
  --binary target/release/herdr \
  --out bench/results-fork.json                  # this branch
python3 bench/compare.py                         # summary table
```

Each herdr run spawns a disposable named session (`herdr-bench-<ts>`) with
`bench-config.toml` (kitty graphics on, nesting allowed, no plugins) and
`HERDR_RENDER_PROF=1`; profiler windows from `herdr-server.log` are saved
into the results JSON. The harness answers DA/DSR/XTWINOPS/kitty queries so
the client believes it is attached to a kitty-like host, and refuses to
proceed if the target session has more than one pane (protects against
accidentally driving a live session — inside a herdr pane the inherited
`HERDR_SOCKET_PATH` points at the live server).

Workloads: idle typing; typing while `churn.py` scrolls text in a split;
typing while `kitty_noise.py` streams 800x600 RGBA frames at 10fps
(~25 MB/s of kitty escapes, every frame content-unique) in a split.

## v0.8.0 vs this branch (2026-08-03, M-series MacBook Pro)

| typing scenario | raw | tmux | herdr 0.8.0 | this branch |
|---|---|---|---|---|
| idle p50 | 0.12ms | 0.26ms | 4.9ms | 4.5ms |
| text churn p50/p95 | — | 2.7/3.0ms | 7.5/24ms | 10.6/23.6ms |
| graphics p50/p95 | — | — | **957/1517ms** (3/40 echoed in 2s) | **7.0/21.5ms** (40/40) |

Host-bound graphics egress: 18.7 MB/s → 1.5 MB/s.
