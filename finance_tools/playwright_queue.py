import time
from threading import Lock


_PLAYWRIGHT_LOCK = Lock()


def run_serialized_playwright(label, runner):
    print(f"[playwright-queue] {label} - in coda per uso esclusivo di Chrome/ChatGPT", flush=True)
    wait_start = time.monotonic()
    last_wait_log = wait_start
    while not _PLAYWRIGHT_LOCK.acquire(timeout=1):
        now = time.monotonic()
        if now - last_wait_log >= 15:
            print(
                f"[playwright-queue] {label} - ancora in coda da {int(now - wait_start)}s; "
                "un altro task sta usando Chrome/ChatGPT",
                flush=True,
            )
            last_wait_log = now
    try:
        waited = int(time.monotonic() - wait_start)
        if waited:
            print(f"[playwright-queue] {label} - coda sbloccata dopo {waited}s", flush=True)
        print(f"[playwright-queue] {label} - avvio Playwright, gli altri tool attendono", flush=True)
        result = runner()
        print(f"[playwright-queue] {label} - Playwright completato", flush=True)
        return result
    finally:
        _PLAYWRIGHT_LOCK.release()
