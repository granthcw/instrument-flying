"""Anonymous reads from the public NOAA S3 buckets.

The NOAA Open Data buckets allow unauthenticated GET and LIST, so this uses
plain HTTPS rather than boto3 -- one less dependency, and it keeps the jobs
runnable anywhere curl works.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
USER_AGENT = "kjyo-backtest/1.0 (+https://github.com/granthcw/instrument-flying)"


class TransientFetchError(RuntimeError):
    """A fetch that is worth retrying (5xx, timeout, reset)."""


def _open(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch(url: str, timeout: int = 60, retries: int = 4) -> bytes:
    """GET a URL, retrying transient failures with exponential backoff.

    A 404 is returned to the caller as None-equivalent by raising
    FileNotFoundError: missing granules are normal (GOES has outages) and the
    ingest jobs need to record them as gaps rather than crash.
    """
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _open(url, timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise FileNotFoundError(url) from exc
            if exc.code < 500 and exc.code != 429:
                raise
            last = exc
        except Exception as exc:  # timeouts, resets, DNS blips
            last = exc
        if attempt < retries:
            time.sleep(delay)
            delay *= 2
    raise TransientFetchError(f"{url}: {last}") from last


def list_keys(bucket: str, prefix: str, timeout: int = 60) -> list[str]:
    """List every key under a prefix, following continuation tokens."""
    keys: list[str] = []
    token: str | None = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        url = f"https://{bucket}.s3.amazonaws.com/?{urllib.parse.urlencode(params)}"
        root = ET.fromstring(fetch(url, timeout=timeout))
        keys.extend(el.text for el in root.iter(f"{_S3_NS}Key") if el.text)
        token_el = root.find(f"{_S3_NS}NextContinuationToken")
        if token_el is None or not token_el.text:
            return keys
        token = token_el.text


def fetch_many(urls: list[str], workers: int = 16, timeout: int = 60):
    """Fetch URLs in parallel, yielding (url, bytes_or_None, error_or_None).

    Missing objects come back as (url, None, None) so callers can count gaps;
    anything else is surfaced as an error for the completeness report.
    """
    def one(u: str):
        try:
            return (u, fetch(u, timeout=timeout), None)
        except FileNotFoundError:
            return (u, None, None)
        except Exception as exc:
            return (u, None, exc)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        yield from pool.map(one, urls)
