"""Plain HTTP GET with retries, shared by the FMCSA and UTC readers.
Standard library only."""

import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "moving-cost-estimator-mover-import"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """A request for public mover data failed."""


def fetch(url, params=None, *, accept="*/*", retries=3, backoff=1.0, timeout=60,
          opener=urllib.request.urlopen, sleep=time.sleep):
    """GET `url` and return the body as bytes. Retries rate-limit and server
    errors, and connection problems, with a growing wait between attempts."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    request = urllib.request.Request(full_url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as err:
            if err.code not in RETRY_STATUSES or attempt == retries:
                raise FetchError(f"HTTP {err.code}") from None
            sleep(_retry_after(err) or backoff * 2 ** attempt)
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == retries:
                reason = getattr(err, "reason", err)
                kind = type(reason).__name__ if isinstance(reason, BaseException) else "network error"
                raise FetchError(f"connection failed ({kind})") from None
            sleep(backoff * 2 ** attempt)


def _retry_after(err):
    try:
        return max(0.0, float(err.headers.get("Retry-After")))
    except (TypeError, ValueError, AttributeError):
        return None
