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
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

#: Statuses that mean "you are not allowed", not "it is not there". These must
#: never be cached as misses and must never be treated as definitive: the SEC
#: blocks an abusive IP with 403 rather than 429, so caching a 403 as "nothing
#: here" would poison every URL attempted during the block and let a fetch
#: report success having collected nothing.
BLOCKED_STATUSES = frozenset({401, 403, 407})

#: Statuses that genuinely mean the resource is absent, and are safe to
#: remember. 400 is here because Yahoo returns it for symbols it does not
#: carry, which on a wide universe is thousands of delisted tickers.
CACHEABLE_MISSES = frozenset({400, 404, 410})


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

    #: Definitive misses expire faster than hits. A ticker that 400s today may
    #: be listed next month, so a month-long negative cache would quietly shrink
    #: the universe; a day is long enough to save a re-run and short enough that
    #: it cannot become a permanent hole in the data.
    miss_ttl_hours = 24.0

    def _remember_miss(self, path: Path, url: str, status: int) -> None:
        """Record that a URL definitively has nothing, so a re-run skips it."""
        try:
            path.write_text(json.dumps({"url": url, "miss": status, "body": None}))
            stale = time.time() - (self.ttl - self.miss_ttl_hours * 3600)
            if stale < time.time():
                os.utime(path, (stale, stale))
        except OSError:  # a cache we cannot write is not a reason to fail
            log.debug("could not cache miss for %s", url)

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
                if blob.get("miss"):
                    return None
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
                if resp.status_code in BLOCKED_STATUSES:
                    # NOT the same as "absent", and the difference is the
                    # difference between a shorter run and a silently empty
                    # one. The SEC answers rate-limit abuse with 403 on the
                    # whole IP -- a block, not a throttle, and never a 429.
                    # Treating that as a definitive miss would cache "nothing
                    # here" for every URL attempted while blocked, and the
                    # fetch would report success having collected nothing.
                    # So: retry, never cache, and say so loudly.
                    log.error(
                        "%s -> %s ACCESS DENIED. This is a block, not a missing "
                        "resource; the whole IP may be blocked. Not caching.",
                        url, resp.status_code,
                    )
                    time.sleep(min(backoff, 60.0))
                    backoff *= 2
                    continue
                if 400 <= resp.status_code < 500:
                    # A client error is an answer, not a failure: the symbol
                    # does not exist, the CIK never filed, the endpoint is
                    # gone. Retrying cannot change it, and on a wide universe
                    # it is the single largest waste of wall clock -- Yahoo
                    # returns 400 for every delisted ticker, and a 5,000-name
                    # pool contains thousands of them. Four attempts with
                    # backoff is fifteen seconds each; this is hours.
                    log.debug("%s -> %s (definitive)", url, resp.status_code)
                    if use_cache and resp.status_code in CACHEABLE_MISSES:
                        self._remember_miss(path, url, resp.status_code)
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

    def get_bytes(self, url: str, *, use_cache: bool = True, timeout: float | None = None) -> bytes | None:
        """GET a binary payload, cached to disk verbatim.

        The JSON cache in :meth:`get` round-trips the body through
        ``json.dumps``, which cannot hold arbitrary bytes. Bulk archives -- the
        SEC's quarterly Form 345 zips, ~14 MB each -- need a separate path.

        Caching these matters more than caching anything else in the codebase.
        An eleven-year fetch is 46 archives; if the run dies at archive 40, the
        difference between a warm cache and a cold one is the difference between
        resuming in seconds and starting over. It also routes through the shared
        rate limiter, which the previous direct-``session.get`` call did not.
        """
        path = self._key(url, None, None).with_suffix(".bin")
        if use_cache and path.exists() and (time.time() - path.stat().st_mtime) < self.ttl:
            try:
                return path.read_bytes()
            except OSError:  # truncated by a killed run; refetch
                path.unlink(missing_ok=True)

        backoff = 1.0
        for attempt in range(self.max_retries):
            self.limiter.acquire()
            try:
                resp = self.session.get(url, timeout=timeout or max(self.timeout, 180.0))
                if resp.status_code == 429 or resp.status_code >= 500:
                    time.sleep(min(float(resp.headers.get("Retry-After", backoff)), 60.0))
                    backoff *= 2
                    continue
                if resp.status_code in BLOCKED_STATUSES:
                    log.error("%s -> %s ACCESS DENIED; the IP may be blocked", url, resp.status_code)
                    time.sleep(min(backoff, 60.0))
                    backoff *= 2
                    continue
                if 400 <= resp.status_code < 500:
                    log.warning("%s -> %s (definitive)", url, resp.status_code)
                    return None
                resp.raise_for_status()
                body = resp.content
                if use_cache:
                    # Write-then-rename so an interrupted write cannot leave a
                    # half-archive that later looks like a cache hit.
                    tmp = path.with_suffix(".part")
                    tmp.write_bytes(body)
                    tmp.replace(path)
                return body
            except requests.RequestException as exc:
                log.warning("%s attempt %d failed: %s", url, attempt + 1, exc)
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
