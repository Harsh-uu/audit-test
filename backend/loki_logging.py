"""Non-blocking Loki logging handler.

Ships Python log records to Grafana Cloud Loki via the HTTP push API.
Records are queued and sent by a background daemon thread so application
request latency is never affected by log shipping.
"""
from __future__ import annotations

import atexit
import gzip
import json
import logging
import queue
import threading
import time

import httpx


class LokiHandler(logging.Handler):
    """Async-safe Loki handler: enqueues records, ships in background batches."""

    def __init__(
        self,
        url: str,
        user: str,
        token: str,
        labels: dict[str, str],
        batch_size: int = 50,
        flush_seconds: float = 2.0,
    ) -> None:
        super().__init__()
        self.push_url = url.rstrip("/") + "/loki/api/v1/push"
        self.auth = (user, token)
        self.labels = labels
        self.batch_size = batch_size
        self.flush_seconds = flush_seconds
        self._q: queue.Queue[logging.LogRecord | None] = queue.Queue(maxsize=10_000)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, name="loki-shipper", daemon=True)
        self._worker.start()
        atexit.register(self.close)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._q.put_nowait(record)
        except queue.Full:
            pass  # Never block the application; silently drop when queue is saturated

    def _run(self) -> None:
        batch: list[logging.LogRecord] = []
        deadline = time.monotonic() + self.flush_seconds
        while not self._stop.is_set():
            timeout = max(0.05, deadline - time.monotonic())
            try:
                record = self._q.get(timeout=timeout)
                if record is None:
                    break
                batch.append(record)
                if len(batch) >= self.batch_size:
                    self._push(batch)
                    batch.clear()
                    deadline = time.monotonic() + self.flush_seconds
            except queue.Empty:
                if batch:
                    self._push(batch)
                    batch.clear()
                deadline = time.monotonic() + self.flush_seconds
        if batch:
            self._push(batch)

    def _push(self, records: list[logging.LogRecord]) -> None:
        values = [
            [str(int(r.created * 1_000_000_000)), self.format(r)]
            for r in records
        ]
        body = {"streams": [{"stream": self.labels, "values": values}]}
        payload = gzip.compress(json.dumps(body, separators=(",", ":")).encode())
        headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}
        for attempt in range(3):
            try:
                resp = httpx.post(
                    self.push_url, content=payload, headers=headers,
                    auth=self.auth, timeout=5.0,
                )
                if resp.is_success:
                    return
                if resp.status_code not in (408, 429) and resp.status_code < 500:
                    return  # Non-retryable error
            except httpx.HTTPError:
                pass
            time.sleep(0.5 * (2 ** attempt))

    def close(self) -> None:
        if not self._stop.is_set():
            self._stop.set()
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
            self._worker.join(timeout=5)
        super().close()


def attach_loki(loki_url: str, loki_user: str, loki_token: str, app_name: str = "supervision2", env: str = "production") -> LokiHandler:
    """Attach a Loki handler to the root logger. Call once at startup."""
    # httpx logs every outgoing HTTP call at INFO ("HTTP Request: POST ... 200 OK") —
    # including the Loki push call this handler itself makes. Since the handler is
    # on the ROOT logger, that self-referential "I just pushed to Loki" message was
    # being re-shipped to Loki as log content: 78% of all shipped lines were pure
    # "HTTP/1.1 204 No Content" noise from httpx describing its own push requests,
    # drowning out real application logs. Silence httpx/httpcore's own INFO chatter.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    handler = LokiHandler(
        url=loki_url,
        user=loki_user,
        token=loki_token,
        labels={"app": app_name, "env": env},
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    return handler
