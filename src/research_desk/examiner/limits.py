"""Usage limits and monitoring for the public demo. No accounts, no keys: quota is per IP.

- Each IP gets PER_IP_DAILY successful examinations per UTC day; the whole site gets GLOBAL_DAILY.
  Failed requests (unknown ticker, empty draft) do not use quota.
- IPs are never stored in the clear: counters key on a salted hash that rotates daily, so
  yesterday's visitors cannot be linked to today's.
- Metrics are aggregates only (requests, status codes, latency, quota refusals, distinct IPs).
State is in memory: the service runs as a single Cloud Run instance, and a restart resets
counters, which errs on the side of the visitor.
"""
import hashlib
import json
import os
import secrets
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

LOCAL_HELP = "Run it on your own machine for unlimited use: see the README's Quick Start."


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def client_ip(headers, peer: str | None) -> str:
    """The caller's IP. Behind Cloud Run's front end the real client is the LAST hop of
    X-Forwarded-For (anything before it can be set by the caller, so it is ignored)."""
    xff = headers.get("x-forwarded-for", "")
    if xff and os.environ.get("TRUST_PROXY", "1") == "1":
        return xff.split(",")[-1].strip()
    return peer or "unknown"


@dataclass
class UsageGuard:
    per_ip_daily: int = 2
    global_daily: int = 300
    enabled: bool = True
    _salt: str = field(default_factory=lambda: secrets.token_hex(16))
    _day: str = field(default_factory=_today)
    _used: Counter = field(default_factory=Counter)
    _total: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @staticmethod
    def from_env() -> "UsageGuard":
        return UsageGuard(per_ip_daily=int(os.environ.get("EXAMINER_PER_IP_DAILY", "2")),
                          global_daily=int(os.environ.get("EXAMINER_GLOBAL_DAILY", "300")),
                          enabled=os.environ.get("EXAMINER_PUBLIC", "0") == "1")

    def _roll(self) -> None:
        today = _today()
        if today != self._day:
            self._day, self._used, self._total = today, Counter(), 0
            self._salt = secrets.token_hex(16)

    def _key(self, ip: str) -> str:
        return hashlib.sha256((self._salt + ip).encode()).hexdigest()[:16]

    def quota(self, ip: str) -> dict:
        with self._lock:
            self._roll()
            used = self._used[self._key(ip)]
            return {"limited": self.enabled, "limit": self.per_ip_daily,
                    "used": used, "remaining": max(0, self.per_ip_daily - used)
                    if self.enabled else None, "resets": "00:00 UTC", "help": LOCAL_HELP}

    def check(self, ip: str) -> str | None:
        """Why this IP may not examine now, or None if it may."""
        if not self.enabled:
            return None
        with self._lock:
            self._roll()
            if self._used[self._key(ip)] >= self.per_ip_daily:
                return (f"You have used your {self.per_ip_daily} free examinations for today. "
                        f"They reset at 00:00 UTC. {LOCAL_HELP}")
            if self._total >= self.global_daily:
                return f"The demo has reached today's limit for all visitors. {LOCAL_HELP}"
        return None

    def consume(self, ip: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._roll()
            self._used[self._key(ip)] += 1
            self._total += 1

    def stats(self) -> dict:
        with self._lock:
            self._roll()
            return {"day": self._day, "examinations": self._total,
                    "distinct_visitors": len(self._used),
                    "visitors_at_limit": sum(v >= self.per_ip_daily for v in self._used.values()),
                    "global_daily_limit": self.global_daily}


@dataclass
class Metrics:
    started: float = field(default_factory=time.time)
    requests: Counter = field(default_factory=Counter)      # (path, status) -> n
    latencies: dict = field(default_factory=dict)            # path -> deque of seconds
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, path: str, status: int, secs: float, ip_hash: str = "") -> None:
        with self._lock:
            self.requests[(path, status)] += 1
            self.latencies.setdefault(path, deque(maxlen=500)).append(secs)
        # one JSON line per request: Cloud Logging indexes these fields
        print(json.dumps({"severity": "ERROR" if status >= 500 else "INFO",
                          "event": "request", "path": path, "status": status,
                          "secs": round(secs, 3), "visitor": ip_hash}), file=sys.stdout,
              flush=True)

    def snapshot(self) -> dict:
        with self._lock:
            by_path: dict[str, dict] = {}
            for (path, status), n in self.requests.items():
                d = by_path.setdefault(path, {"total": 0, "status": {}})
                d["total"] += n
                d["status"][str(status)] = n
            for path, lat in self.latencies.items():
                s = sorted(lat)
                by_path.setdefault(path, {"total": 0, "status": {}}).update(
                    p50_secs=round(s[len(s) // 2], 3),
                    p95_secs=round(s[min(len(s) - 1, int(len(s) * 0.95))], 3))
            return {"uptime_secs": round(time.time() - self.started), "endpoints": by_path}
