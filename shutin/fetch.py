import time
from urllib.parse import urlparse

from curl_cffi import requests

_last_hit: dict[str, float] = {}


def get(url, *, params=None, min_gap=1.0, attempts=3, **kw):
    """Polite impersonating GET: >=min_gap s per host, backoff on 5xx, raise fast on 4xx."""
    host = urlparse(url).netloc
    last_err = None
    for attempt in range(attempts):
        gap = _last_hit.get(host, -min_gap) + min_gap - time.monotonic()
        if gap > 0:
            time.sleep(gap)
        _last_hit[host] = time.monotonic()
        try:
            r = requests.get(url, params=params, impersonate="chrome", timeout=30, **kw)
        except Exception as e:  # network-level failure -> retryable
            last_err = e
        else:
            if r.status_code < 500:
                r.raise_for_status()  # 4xx raises here, no retry
                return r
            last_err = RuntimeError(f"HTTP {r.status_code} from {url}")
        if attempt < attempts - 1:
            time.sleep(2**attempt)
    raise last_err
