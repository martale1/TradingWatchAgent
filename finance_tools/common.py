import os
import subprocess
import sys
import time
from queue import Empty, Queue
from pathlib import Path
from threading import Thread


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = Path(sys.executable)


def load_env_file(path=None):
    env_path = Path(path) if path else PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _kill_process_tree(process):
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.kill()


def _short_line(value, limit=220):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def run_python_script(args, timeout_seconds=300, progress_label=None, heartbeat_seconds=20):
    command = [str(PYTHON_EXE), *args]
    label = progress_label or (Path(args[0]).name if args else "python-script")
    print(f"[subprocess] {label} - avvio: {' '.join(command)}", flush=True)
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output_queue = Queue()
    stdout_lines = []
    stderr_lines = []

    def reader(stream_name, stream):
        try:
            for line in stream:
                output_queue.put((stream_name, line.rstrip("\n")))
        finally:
            output_queue.put((stream_name, None))

    Thread(target=reader, args=("stdout", process.stdout), daemon=True).start()
    Thread(target=reader, args=("stderr", process.stderr), daemon=True).start()

    deadline = time.monotonic() + timeout_seconds
    last_heartbeat = time.monotonic()
    start = time.monotonic()
    streams_done = set()
    last_output = ""

    while True:
        if time.monotonic() >= deadline:
            _kill_process_tree(process)
            elapsed = int(time.monotonic() - start)
            print(f"[subprocess] {label} - TIMEOUT dopo {elapsed}s, processo terminato", flush=True)
            return {
                "returncode": -1,
                "stdout": "\n".join(stdout_lines),
                "stderr": "\n".join(stderr_lines + [f"Timeout dopo {timeout_seconds}s"]),
                "command": " ".join(command),
            }

        try:
            stream_name, line = output_queue.get(timeout=0.5)
        except Empty:
            if process.poll() is not None and len(streams_done) == 2:
                break
            if time.monotonic() - last_heartbeat >= heartbeat_seconds:
                elapsed = int(time.monotonic() - start)
                suffix = f" | ultimo output: {_short_line(last_output, 120)}" if last_output else ""
                print(f"[subprocess] {label} - ancora in corso da {elapsed}s{suffix}", flush=True)
                last_heartbeat = time.monotonic()
            continue

        if line is None:
            streams_done.add(stream_name)
            if process.poll() is not None and len(streams_done) == 2:
                break
            continue

        last_output = line
        if stream_name == "stdout":
            stdout_lines.append(line)
        else:
            stderr_lines.append(line)
        print(f"[subprocess] {label} {stream_name}> {_short_line(line)}", flush=True)

    return_code = process.wait()
    elapsed = int(time.monotonic() - start)
    print(f"[subprocess] {label} - completato in {elapsed}s exit={return_code}", flush=True)
    return {
        "returncode": return_code,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
        "command": " ".join(command),
    }
