#!/usr/bin/env python3
"""Capture REAL tool output into testdata/, so the parsers are tested against the format
they actually meet rather than against a string someone imagined.

    ssh htpc-01 'python3 capture_fixtures.py'      # writes ~/testdata/ on the host
    scp -r htpc-01:testdata/ .                      # bring it back

Runs ON htpc-01. Needs the card free, so it stops llama-swap.service for ~3 minutes and
restores it on any exit — including a dropped connection, since bench.service_stopped
converts SIGHUP into a SystemExit that runs the finally.

WHY THIS EXISTS
---------------
Every parser fixture in test_bench.py was hand-written, and the one parser that has
actually broken in production was the startup-log filter: it matched "kv cache" when the
real line is `llama_kv_cache:` — underscore, not space — so `KV self size` was silently
never captured, and the fit search that needed it came up empty on the host. A
hand-written fixture could not have caught that, because the same wrong assumption
produces both the parser and the fixture.

Re-run this when the images change. The captured files are small and are the evidence
that the parsers still match reality.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import bench
import prompts
import run_matrix as rm

CONTAINER = "bench-fixtures"        # never llama-bench or llama-swap
OUT = Path(__file__).resolve().parent / "testdata"

# Small and fast: the fixtures are about output FORMAT, not about performance. gemma at a
# tiny context loads in ~30s and emits exactly the same startup-log structure as -c 65536.
FIXTURE_MODEL = "gemma"
FIXTURE_CTX = 4096


def sh(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def write(name: str, content: str) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(content)
    print(f"  wrote {name}  ({len(content)} bytes, {len(content.splitlines())} lines)")


class Args:
    """Stand-in for the argparse namespace server_argv reads."""
    ctx, fa, ub, kv, verbose = FIXTURE_CTX, "1", "", "", True


def capture_backend(backend: str) -> bool:
    print(f"\n=== {backend} ===")
    sh(["sudo", "podman", "rm", "-f", CONTAINER])
    argv = [a if a != rm.CONTAINER else CONTAINER for a in rm.container_argv(backend)]
    if sh(argv).returncode != 0:
        print(f"  !! container would not start for {backend}")
        return False
    box = bench.Box(CONTAINER)

    write(f"list-devices.{backend}.txt",
          box.exec("/app/llama-server", "--list-devices").stdout)

    # amd-smi ships in the ROCm image only — capturing that asymmetry IS one of the
    # facts under test, so the vulkan side records its absence rather than skipping.
    if box.has("amd-smi"):
        write("amd-smi-metric-mem.rocm.txt",
              box.exec("amd-smi", "metric", "-g", "0", "--mem").stdout)
    else:
        print(f"  amd-smi absent on {backend} (expected — that is why VRAM comes from "
              "host sysfs)")

    gguf, sampler = bench.MODELS[FIXTURE_MODEL]
    _, startlog = bench.run_paths()
    bench.start_server(box, gguf, sampler, Args(), startlog)
    if not bench.wait_healthy(box):
        print(f"  !! server never became healthy on {backend}")
        print(box.exec("cat", startlog).stdout[-1500:])
        sh(["sudo", "podman", "rm", "-f", CONTAINER])
        return False

    # The whole startup log, untruncated. select_startup_lines() is tested against this,
    # so the fixture must contain the noise the filter has to survive — ~50 "layer N
    # assigned to device" lines that once swamped the KV line out of a truncated view.
    write(f"startup.{backend}.log", box.exec("cat", startlog).stdout)

    if box.has("amd-smi"):
        write("amd-smi-process.rocm.txt",
              box.exec("amd-smi", "process", "-g", "0").stdout)

    if backend == "rocm":       # one completion is enough; the JSON shape is not per-backend
        with tempfile.TemporaryDirectory() as td:
            host = Path(td)
            prompts.write_corpus(host, 1, 40, False, 32)
            cdir = "/tmp/fixtures"
            box.exec("mkdir", "-p", cdir)
            box.cp(host / "v0.json", f"{cdir}/")
            r = box.exec("curl", "-s", "--max-time", "600",
                         f"localhost:{bench.PORT}/v1/chat/completions",
                         "-H", "Content-Type: application/json",
                         "-d", f"@{cdir}/v0.json")
            write("completion.json", r.stdout)

    box.exec("pkill", "-f", f"llama-server --port {bench.PORT}")
    sh(["sudo", "podman", "rm", "-f", CONTAINER])
    return True


def capture_host() -> None:
    print("\n=== host ===")
    for d in sorted(Path("/sys/class/drm").glob("card[0-9]/device")):
        try:
            used = (d / "mem_info_vram_used").read_text().strip()
            total = (d / "mem_info_vram_total").read_text().strip()
        except OSError:
            continue
        # Bytes, deliberately raw: the unit conversion is the thing being tested. Every
        # historical row and the 1.5 GB floor are MB; without the //1048576 the floor
        # check silently never fires.
        write("sysfs-vram.txt", f"{d}\nmem_info_vram_used={used}\n"
                                f"mem_info_vram_total={total}\n")
        return
    print("  !! no amdgpu card found under /sys/class/drm")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backends", default="rocm,vulkan")
    a = ap.parse_args()

    print(f"capturing into {OUT}")
    ok = True
    with bench.service_stopped():
        time.sleep(3)               # let the deployed container release the card
        capture_host()
        for backend in a.backends.split(","):
            ok &= capture_backend(backend)
    sh(["sudo", "podman", "rm", "-f", CONTAINER])

    print(f"\n{'captured' if ok else 'INCOMPLETE — some captures failed'}")
    for f in sorted(OUT.glob("*")):
        print(f"  {f.name}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
