from threading import Lock


_PLAYWRIGHT_LOCK = Lock()


def run_serialized_playwright(label, runner):
    print(f"[playwright-queue] {label} - in coda per uso esclusivo di Chrome/ChatGPT", flush=True)
    with _PLAYWRIGHT_LOCK:
        print(f"[playwright-queue] {label} - avvio Playwright, gli altri tool attendono", flush=True)
        result = runner()
        print(f"[playwright-queue] {label} - Playwright completato", flush=True)
        return result
