import os
import sys

from .limits import apply_limits

def main():
    if len(sys.argv) < 5:
        raise SystemExit("usage: launch_worker CPU_SECONDS MEM_BYTES WORKER_ARGS...")
    cpu_seconds = int(sys.argv[1])
    mem_bytes = int(sys.argv[2])
    worker_args = sys.argv[3:]
    if not apply_limits(cpu_seconds, mem_bytes):
        raise SystemExit("POSIX resource limits are unavailable")
    os.execv(
        sys.executable,
        [sys.executable, "-B", "-m", "sandbox.bot_worker", *worker_args],
    )

if __name__ == "__main__":
    main()
