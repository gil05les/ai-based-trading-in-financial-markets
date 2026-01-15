# Global locks for concurrent services
from __future__ import annotations

import contextlib
import time
from typing import Iterator

import psycopg2
import structlog

from backend.config import settings


logger = structlog.get_logger(__name__)


class GlobalPromptLock:
    # Uses Postgres advisory locks for distributed sync

    def __init__(
        self,
        dsn: str,
        lock_key: int = 42,
        retry_interval: float = 0.5,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.dsn = dsn
        self.lock_key = lock_key
        self.retry_interval = retry_interval
        self.timeout_seconds = timeout_seconds
        logger.info(
            "Prompt lock initialized",
            lock_key=lock_key,
            retry_interval=retry_interval,
            timeout_seconds=timeout_seconds,
        )

    def _connect(self):
        conn = psycopg2.connect(self.dsn)
        conn.autocommit = True
        return conn, conn.cursor()

    def _wait_for_lock(self, cursor) -> bool:
        start = time.time()
        while True:
            cursor.execute("SELECT pg_try_advisory_lock(%s);", (self.lock_key,))
            acquired = cursor.fetchone()[0]
            if acquired:
                logger.debug("Prompt lock acquired")
                return True

            if time.time() - start > self.timeout_seconds:
                return False

            time.sleep(self.retry_interval)

    def _release(self, cursor) -> None:
        cursor.execute("SELECT pg_advisory_unlock(%s);", (self.lock_key,))
        logger.debug("Prompt lock released")

    @contextlib.contextmanager
    def acquire(self) -> Iterator[None]:
        # Lock/unlock wrapper
        conn = None
        cursor = None
        acquired = False
        try:
            conn, cursor = self._connect()
            acquired = self._wait_for_lock(cursor)
            if not acquired:
                raise TimeoutError("Timed out acquiring global prompt lock")
            yield
        finally:
            if cursor is not None:
                try:
                    if acquired:
                        self._release(cursor)
                except Exception as exc:  # pragma: no cover - best effort logging
                    logger.warning("Failed to release prompt lock", error=str(exc))
                cursor.close()
            if conn is not None:
                conn.close()


prompt_lock = GlobalPromptLock(settings.postgres_url)

