from __future__ import annotations

import hashlib
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .parsing import normalize_for_match

ProviderAvailability = Literal["allowed", "cooldown", "negative_cache"]
ProviderHealthState = Literal["idle", "healthy", "degraded", "cooldown"]


@dataclass(frozen=True, slots=True)
class ProviderReliabilityPolicy:
    minimum_interval_seconds: float = 0.15
    failure_cooldown_seconds: float = 30.0
    maximum_cooldown_seconds: float = 300.0
    negative_cache_seconds: float = 120.0
    maximum_negative_entries: int = 4_096

    def __post_init__(self) -> None:
        numeric_values = (
            self.minimum_interval_seconds,
            self.failure_cooldown_seconds,
            self.maximum_cooldown_seconds,
            self.negative_cache_seconds,
        )
        if any(not math.isfinite(value) or value < 0 for value in numeric_values):
            raise ValueError("来源可靠性时间参数必须是非负有限数字。")
        if self.maximum_cooldown_seconds < self.failure_cooldown_seconds:
            raise ValueError("最大冷却时间不能小于基础冷却时间。")
        if self.maximum_negative_entries < 1:
            raise ValueError("负缓存条目上限必须大于 0。")


@dataclass(frozen=True, slots=True)
class ProviderCallPermit:
    availability: ProviderAvailability
    wait_seconds: float = 0.0

    @property
    def allowed(self) -> bool:
        return self.availability == "allowed"


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    state: ProviderHealthState
    attempts: int
    successes: int
    failures: int
    consecutive_failures: int
    cooldown_skips: int
    negative_cache_hits: int
    rate_limit_waits: int
    cooldown_remaining_seconds: int
    last_error: str | None

    def to_dict(self) -> dict[str, int | str | None]:
        labels = {
            "idle": "尚未请求",
            "healthy": "运行正常",
            "degraded": "等待恢复",
            "cooldown": "暂时冷却",
        }
        return {
            "status": self.state,
            "status_label": labels[self.state],
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "consecutive_failures": self.consecutive_failures,
            "cooldown_skips": self.cooldown_skips,
            "negative_cache_hits": self.negative_cache_hits,
            "rate_limit_waits": self.rate_limit_waits,
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds,
            "last_error": self.last_error,
        }


@dataclass(slots=True)
class _ProviderRuntimeState:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    cooldown_skips: int = 0
    negative_cache_hits: int = 0
    rate_limit_waits: int = 0
    next_call_at: float = 0.0
    cooldown_until: float = 0.0
    last_success_at: float = 0.0
    last_failure_at: float = 0.0
    last_error: str | None = None


class ProviderReliabilityController:
    """Share per-provider throttling and health across resolver instances."""

    def __init__(
        self,
        policy: ProviderReliabilityPolicy | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.policy = policy or ProviderReliabilityPolicy()
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.RLock()
        self._states: dict[str, _ProviderRuntimeState] = {}
        self._negative_cache: dict[tuple[str, str, str], float] = {}

    @staticmethod
    def _query_key(provider_id: str, operation: str, query: str) -> tuple[str, str, str]:
        normalized = normalize_for_match(query)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return provider_id, operation, digest

    def _state(self, provider_id: str) -> _ProviderRuntimeState:
        return self._states.setdefault(provider_id, _ProviderRuntimeState())

    def before_call(
        self,
        provider_id: str,
        operation: str,
        query: str,
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> ProviderCallPermit:
        now = self._monotonic()
        cache_key = self._query_key(provider_id, operation, query)
        with self._lock:
            state = self._state(provider_id)
            negative_until = self._negative_cache.get(cache_key, 0.0)
            if negative_until > now:
                state.negative_cache_hits += 1
                return ProviderCallPermit("negative_cache")
            self._negative_cache.pop(cache_key, None)

            if state.cooldown_until > now:
                state.cooldown_skips += 1
                return ProviderCallPermit("cooldown")

            wait_seconds = max(0.0, state.next_call_at - now)
            state.next_call_at = max(now, state.next_call_at) + self.policy.minimum_interval_seconds
            state.attempts += 1
            if wait_seconds > 0:
                state.rate_limit_waits += 1

        if checkpoint is not None:
            checkpoint()
        if wait_seconds > 0:
            self._sleep(wait_seconds)
        if checkpoint is not None:
            checkpoint()
        return ProviderCallPermit("allowed", wait_seconds)

    def record_success(self, provider_id: str) -> None:
        now = self._monotonic()
        with self._lock:
            state = self._state(provider_id)
            state.successes += 1
            state.consecutive_failures = 0
            state.cooldown_until = 0.0
            state.last_success_at = now
            state.last_error = None

    def record_no_result(self, provider_id: str, operation: str, query: str) -> None:
        self.record_success(provider_id)
        if self.policy.negative_cache_seconds <= 0:
            return
        now = self._monotonic()
        cache_key = self._query_key(provider_id, operation, query)
        with self._lock:
            self._negative_cache[cache_key] = now + self.policy.negative_cache_seconds
            self._prune_negative_cache_locked(now)

    def record_failure(self, provider_id: str, error: str) -> None:
        now = self._monotonic()
        with self._lock:
            state = self._state(provider_id)
            state.failures += 1
            state.consecutive_failures += 1
            multiplier = 2 ** max(0, state.consecutive_failures - 1)
            cooldown = min(
                self.policy.failure_cooldown_seconds * multiplier,
                self.policy.maximum_cooldown_seconds,
            )
            state.cooldown_until = max(state.cooldown_until, now + cooldown)
            state.last_failure_at = now
            state.last_error = str(error)[:400]

    def health(self, provider_id: str) -> ProviderHealth:
        now = self._monotonic()
        with self._lock:
            state = self._state(provider_id)
            cooldown_remaining = max(0.0, state.cooldown_until - now)
            if cooldown_remaining > 0:
                health_state: ProviderHealthState = "cooldown"
            elif state.successes == 0 and state.failures == 0:
                health_state = "idle"
            elif state.last_failure_at > state.last_success_at:
                health_state = "degraded"
            else:
                health_state = "healthy"
            return ProviderHealth(
                state=health_state,
                attempts=state.attempts,
                successes=state.successes,
                failures=state.failures,
                consecutive_failures=state.consecutive_failures,
                cooldown_skips=state.cooldown_skips,
                negative_cache_hits=state.negative_cache_hits,
                rate_limit_waits=state.rate_limit_waits,
                cooldown_remaining_seconds=math.ceil(cooldown_remaining),
                last_error=state.last_error,
            )

    def _prune_negative_cache_locked(self, now: float) -> None:
        expired = [key for key, expires_at in self._negative_cache.items() if expires_at <= now]
        for key in expired:
            self._negative_cache.pop(key, None)
        overflow = len(self._negative_cache) - self.policy.maximum_negative_entries
        if overflow <= 0:
            return
        for key, _ in sorted(self._negative_cache.items(), key=lambda item: item[1])[:overflow]:
            self._negative_cache.pop(key, None)
