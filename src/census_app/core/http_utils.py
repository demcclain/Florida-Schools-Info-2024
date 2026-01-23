"""HTTP helpers with retries for API calls."""
from __future__ import annotations

import time
from typing import Any

import requests

from .config import TIMEOUT

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "BPA-ACS/1.0"})


def http_get_json(url: str, params: dict, retries: int = 3, timeout: int = TIMEOUT) -> Any:
    """GET JSON with basic retry/backoff for transient errors."""
    backoff = 0.6
    for i in range(retries):
        try:
            r = _SESSION.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.Timeout, requests.ConnectionError):
            if i + 1 == retries:
                raise
            time.sleep(backoff)
            backoff *= 1.7
        except requests.HTTPError as e:
            code = getattr(e.response, "status_code", 0)
            if code in (429, 500, 502, 503, 504) and i + 1 < retries:
                time.sleep(backoff)
                backoff *= 1.7
                continue
            raise
