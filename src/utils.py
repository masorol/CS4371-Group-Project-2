"""Shared helpers: environment keys, disk cache, throttling, call counting,
the LLM client (Groq, with OpenRouter as backup) and the number check.

Every task can import from here so the whole team uses one LLM client and
one number check (the assignment asks for "the same number check" in
Tasks 2, 5 and 8).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
OUTPUT_DIR = ROOT / "outputs"

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openai/gpt-oss-120b:free"


# --------------------------------------------------------------------------
# Environment variables
# --------------------------------------------------------------------------
def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines from .env into os.environ (without overwriting
    variables that are already set). Written by hand so we need no extra
    package."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def get_key(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat(timespec="seconds")


def age_text(retrieved_at: str | None) -> str:
    """'3 min old', '2 h old', '4 days old' for a stored ISO timestamp."""
    if not retrieved_at:
        return "age unknown"
    try:
        then = datetime.fromisoformat(str(retrieved_at))
    except ValueError:
        return "age unknown"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = max(0, (now_utc() - then).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min old"
    if secs < 86400:
        return f"{int(secs // 3600)} h old"
    return f"{int(secs // 86400)} days old"


# --------------------------------------------------------------------------
# Call statistics (Task 7 needs time and number of API calls per request)
# --------------------------------------------------------------------------
@dataclass
class CallStats:
    api_calls: int = 0
    cache_hits: int = 0
    by_service: dict = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)

    def record(self, service: str, from_cache: bool) -> None:
        if from_cache:
            self.cache_hits += 1
        else:
            self.api_calls += 1
            self.by_service[service] = self.by_service.get(service, 0) + 1

    def seconds(self) -> float:
        return round(time.perf_counter() - self.started, 2)

    def as_dict(self) -> dict:
        return {
            "api_calls": self.api_calls,
            "cache_hits": self.cache_hits,
            "by_service": dict(self.by_service),
            "seconds": self.seconds(),
        }


STATS = CallStats()


def reset_stats() -> CallStats:
    """Start counting for a new user request."""
    global STATS
    STATS = CallStats()
    return STATS


# --------------------------------------------------------------------------
# Disk cache: every API response is saved with the time it was received
# --------------------------------------------------------------------------
def cache_key(service: str, payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{service}|{text}".encode("utf-8")).hexdigest()[:32]


def cache_path(service: str, payload: dict) -> Path:
    return CACHE_DIR / service / f"{cache_key(service, payload)}.json"


def cache_read(service: str, payload: dict) -> dict | None:
    path = cache_path(service, payload)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cache_write(service: str, payload: dict, response) -> dict:
    record = {"retrieved_at": now_iso(), "service": service,
              "request": payload, "response": response}
    path = cache_path(service, payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


_last_call: dict[str, float] = {}


def throttle(service: str, min_gap: float = 1.0) -> None:
    """Wait so that calls to the same service are at least min_gap seconds apart."""
    last = _last_call.get(service)
    if last is not None:
        wait = min_gap - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_call[service] = time.monotonic()


# --------------------------------------------------------------------------
# LLM client
# --------------------------------------------------------------------------
class LLMError(RuntimeError):
    pass


def _post_chat(url: str, key: str, body: dict, timeout: int = 60) -> dict:
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise LLMError(f"{url} returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def call_llm(system: str, user: str, json_mode: bool = False,
             use_cache: bool = True) -> dict:
    """One chat call to the main LLM (gpt-oss-120b on Groq), temperature 0.

    Falls back to OpenRouter only if Groq fails and an OpenRouter key exists.
    Returns {"text", "provider", "model", "retrieved_at", "from_cache"}.
    """
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    attempts = []
    if get_key("GROQ_API_KEY"):
        attempts.append(("groq", GROQ_URL, get_key("GROQ_API_KEY"), GROQ_MODEL))
    if get_key("OPENROUTER_API_KEY"):
        attempts.append(("openrouter", OPENROUTER_URL, get_key("OPENROUTER_API_KEY"),
                         OPENROUTER_MODEL))

    errors = []
    # Cached answers are reused even when no key is set (e.g. a blocked team).
    for service, url, key, model in attempts or [("groq", GROQ_URL, None, GROQ_MODEL)]:
        body = {"model": model, "messages": messages, "temperature": 0}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if use_cache:
            hit = cache_read(service, body)
            if hit is not None:
                STATS.record(service, from_cache=True)
                return {"text": hit["response"], "provider": service, "model": model,
                        "retrieved_at": hit["retrieved_at"], "from_cache": True}
        if key is None:
            errors.append("no GROQ_API_KEY or OPENROUTER_API_KEY set in .env")
            continue
        try:
            throttle(service)
            STATS.record(service, from_cache=False)
            data = _post_chat(url, key, body)
            text = data["choices"][0]["message"]["content"] or ""
        except (requests.RequestException, LLMError, KeyError, IndexError) as exc:
            errors.append(f"{service}: {exc}")
            continue
        record = cache_write(service, body, text)
        return {"text": text, "provider": service, "model": model,
                "retrieved_at": record["retrieved_at"], "from_cache": False}
    raise LLMError("LLM unavailable: " + "; ".join(errors))


def parse_json_reply(text: str) -> dict:
    """Parse a JSON object from an LLM reply, tolerating ```json fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")
    return obj


# --------------------------------------------------------------------------
# Number check: every number in an LLM answer must appear in the data sent
# --------------------------------------------------------------------------
_NUM_RE = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?%?")


def _to_float(token: str) -> float | None:
    token = token.replace("$", "").replace(",", "").replace("%", "").lstrip("+")
    try:
        return float(token)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[str]:
    """All number tokens in a piece of text ('$1,234.50', '12%', '3.5')."""
    # Ignore markdown list markers such as '1. ' at the start of a line.
    text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)
    return [m.group(0) for m in _NUM_RE.finditer(text)]


def _collect_numbers(obj, out: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            val = _to_float(tok)
            if val is not None:
                out.add(val)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _collect_numbers(k, out)
            _collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, out)


def _matches(value: float, allowed: set[float]) -> bool:
    """A number in the answer matches a source number if it equals it or is
    that number rounded to 0, 1 or 2 decimals (LLMs round 12.347 to 12.3)."""
    for src in allowed:
        if abs(value - src) < 1e-9:
            return True
        for digits in (0, 1, 2):
            if abs(round(src, digits) - value) < 1e-9:
                return True
        # shares stored as fractions but written as percentages (0.12 -> 12%)
        if 0 < abs(src) < 1 and any(abs(round(src * 100, d) - value) < 1e-9 for d in (0, 1, 2)):
            return True
    return False


def number_check(answer: str, data, extra_allowed=()) -> tuple[bool, list[str]]:
    """Return (passed, offending_numbers).

    data: the exact rows/JSON sent to the LLM.
    extra_allowed: numbers the user gave (nights, guests, budget, dates).
    """
    allowed: set[float] = set()
    _collect_numbers(data, allowed)
    _collect_numbers(list(extra_allowed), allowed)
    bad = []
    for tok in extract_numbers(answer):
        val = _to_float(tok)
        if val is None or not _matches(val, allowed):
            bad.append(tok)
    return (not bad, bad)
