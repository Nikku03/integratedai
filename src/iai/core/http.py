"""Polite, cached HTTP.

Every public source used here has a rate limit and a terms-of-service. The SEC
asks for <=10 req/s and a real User-Agent; OpenSky throttles anonymous callers
hard; CourtListener meters by token. This module centralises throttling,
retries and on-disk caching so no individual source adapter has to get it right
independently, and so a backtest re-run does not re-hammer anyone's servers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket limiter, safe across threads."""

    def __init__(self, rate_per_sec: float) -> None:
        self.min_interval = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._last + self.min_interval - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._last = now


class HttpClient:
    """Requests wrapper with retry, throttle and a content-addressed disk cache."""

    def __init__(
        self,
        cache_dir: Path,
        user_agent: str,
        rate_per_sec: float = 5.0,
        ttl_hours: float = 12.0,
        timeout: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.limiter = RateLimiter(rate_per_sec)
        self.ttl = ttl_hours * 3600
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        )

    def _key(self, url: str, params: dict | None, headers: dict | None) -> Path:
        raw = json.dumps(
            [url, sorted((params or {}).items()), sorted((headers or {}).items())],
            default=str,
            sort_keys=True,
        )
        return self.cache_dir / f"{hashlib.sha256(raw.encode()).hexdigest()[:32]}.json"

    def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        *,
        parse: str = "json",
        use_cache: bool = True,
    ) -> Any:
        """GET with cache. ``parse`` is ``"json"``, ``"text"`` or ``"raw"``.

        Returns ``None`` on unrecoverable failure rather than raising: one dead
        source should degrade the feature set, not abort the whole run.
        """
        path = self._key(url, params, headers)
        if use_cache and path.exists() and (time.time() - path.stat().st_mtime) < self.ttl:
            try:
                blob = json.loads(path.read_text())
                return blob["body"] if parse != "json" else blob["body"]
            except Exception:  # noqa: BLE001 - corrupt cache entry, just refetch
                path.unlink(missing_ok=True)

        backoff = 1.0
        for _attempt in range(self.max_retries):
            self.limiter.acquire()
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    retry_after = float(resp.headers.get("Retry-After", backoff))
                    log.warning("%s -> %s, retrying in %.1fs", url, resp.status_code, retry_after)
                    time.sleep(min(retry_after, 60.0))
                    backoff *= 2
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                body = resp.json() if parse == "json" else resp.text
                if use_cache:
                    path.write_text(json.dumps({"url": url, "body": body}))
                return body
            except requests.RequestException as exc:
                log.warning("%s attempt %d failed: %s", url, _attempt + 1, exc)
                time.sleep(backoff)
                backoff *= 2
        log.error("giving up on %s after %d attempts", url, self.max_retries)
        return None

    def get_many(
        self,
        urls: list[str],
        *,
        parse: str = "json",
        workers: int = 8,
        headers: dict | None = None,
        progress_every: int = 500,
    ) -> dict[str, object]:
        """Fetch many URLs concurrently, returning ``{url: body}``.

        The shared :class:`RateLimiter` still applies across threads, so the
        aggregate request rate stays inside the source's published limit no
        matter how many workers are used -- the concurrency hides latency, it
        does not raise throughput past what the host allows. That distinction
        matters: the SEC publishes a 10 req/s ceiling and enforces it with
        blocks, not with 429s.

        Failures return ``None`` for that URL rather than aborting the batch.
        """
        out: dict[str, object] = {}
        if not urls:
            return out
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.get, u, headers=headers, parse=parse): u for u in urls
            }
            for fut in as_completed(futures):
                url = futures[fut]
                try:
                    out[url] = fut.result()
                except Exception:  # noqa: BLE001 - one bad URL must not kill the batch
                    log.exception("unhandled error fetching %s", url)
                    out[url] = None
                done += 1
                if progress_every and done % progress_every == 0:
                    log.info("fetched %d/%d", done, len(urls))
        return out
