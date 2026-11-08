"""Shared helpers for calling Gemini safely: retries, back-off and fallback models."""
import random
import re
import time

MAX_WAIT_SECONDS = 30   # a longer wait (e.g. daily quota) is not worth blocking a student for
TRANSIENT_CODES = {500, 502, 503, 504}


def is_quota_error(err) -> bool:
    """429: too many requests / quota exceeded."""
    return getattr(err, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(err)


def is_transient_error(err) -> bool:
    """Temporary server-side problem (overloaded, unavailable, timeout...). Worth retrying."""
    if getattr(err, "code", None) in TRANSIENT_CODES:
        return True
    s = str(err)
    return any(k in s for k in ("UNAVAILABLE", "DEADLINE_EXCEEDED", "high demand", "overloaded"))


def retry_delay(err, default: float = 10.0) -> float:
    """Seconds Gemini asks us to wait, parsed from the error text."""
    s = str(err)
    m = re.search(r"retry in ([\d.]+)\s*(ms|s)\b", s, re.I)
    if m:
        v = float(m.group(1))
        return v / 1000 if m.group(2).lower() == "ms" else v
    m = re.search(r"retryDelay[^\d]*([\d.]+)s", s)
    return float(m.group(1)) if m else default


def call_with_retry(call, models, attempts_per_model: int = 3):
    """call(model) -> result. Tries each model in order.
      - quota (429)       : waits what Gemini asks; if too long, moves to the next model
      - transient (503...) : back-off 2s, 4s..., then moves to the next model
      - any other error    : stops immediately (retrying would not help)
    Returns (result, None, model_used) on success, or (None, last_error, None)."""
    last_err = None
    for model in models:
        for attempt in range(attempts_per_model):
            try:
                return call(model), None, model
            except Exception as e:
                last_err = e
                last = attempt == attempts_per_model - 1
                if is_quota_error(e):
                    wait = retry_delay(e) + 1
                    if wait > MAX_WAIT_SECONDS or last:
                        break
                    time.sleep(wait)
                elif is_transient_error(e):
                    if last:
                        break
                    time.sleep(2 * 2 ** attempt + random.random())
                else:
                    return None, e, None
    return None, last_err, None
