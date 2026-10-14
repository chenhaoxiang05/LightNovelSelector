import math
import unittest

from lightnovel_selector.provider_reliability import (
    ProviderCallPermit,
    ProviderHealth,
    ProviderReliabilityController,
    ProviderReliabilityPolicy,
)


class TestProviderReliabilityPolicy(unittest.TestCase):
    def test_default_values(self) -> None:
        policy = ProviderReliabilityPolicy()
        self.assertEqual(policy.minimum_interval_seconds, 0.15)
        self.assertEqual(policy.failure_cooldown_seconds, 30.0)
        self.assertEqual(policy.maximum_cooldown_seconds, 300.0)
        self.assertEqual(policy.negative_cache_seconds, 120.0)
        self.assertEqual(policy.maximum_negative_entries, 4096)

    def test_validation_negative_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "来源可靠性时间参数必须是非负有限数字。"):
            ProviderReliabilityPolicy(minimum_interval_seconds=-1.0)

        with self.assertRaisesRegex(ValueError, "来源可靠性时间参数必须是非负有限数字。"):
            ProviderReliabilityPolicy(failure_cooldown_seconds=-0.5)

    def test_validation_infinite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "来源可靠性时间参数必须是非负有限数字。"):
            ProviderReliabilityPolicy(minimum_interval_seconds=math.inf)

        with self.assertRaisesRegex(ValueError, "来源可靠性时间参数必须是非负有限数字。"):
            ProviderReliabilityPolicy(failure_cooldown_seconds=math.nan)

    def test_validation_cooldown_constraints(self) -> None:
        with self.assertRaisesRegex(ValueError, "最大冷却时间不能小于基础冷却时间。"):
            ProviderReliabilityPolicy(failure_cooldown_seconds=30.0, maximum_cooldown_seconds=10.0)

    def test_validation_negative_entries_constraints(self) -> None:
        with self.assertRaisesRegex(ValueError, "负缓存条目上限必须大于 0。"):
            ProviderReliabilityPolicy(maximum_negative_entries=0)

        with self.assertRaisesRegex(ValueError, "负缓存条目上限必须大于 0。"):
            ProviderReliabilityPolicy(maximum_negative_entries=-1)

class TestProviderReliabilityController(unittest.TestCase):
    def setUp(self) -> None:
        self.current_time = 1000.0
        self.sleep_calls: list[float] = []

        def mock_monotonic() -> float:
            return self.current_time

        def mock_sleep(seconds: float) -> None:
            self.sleep_calls.append(seconds)
            self.current_time += seconds

        self.policy = ProviderReliabilityPolicy(
            minimum_interval_seconds=1.0,
            failure_cooldown_seconds=10.0,
            maximum_cooldown_seconds=60.0,
            negative_cache_seconds=30.0,
            maximum_negative_entries=5,
        )
        self.controller = ProviderReliabilityController(
            policy=self.policy,
            monotonic=mock_monotonic,
            sleep=mock_sleep,
        )

    def test_health_states(self) -> None:
        # Initial state should be idle
        health = self.controller.health("test_provider")
        self.assertEqual(health.state, "idle")

        # After success, state should be healthy
        self.controller.record_success("test_provider")
        health = self.controller.health("test_provider")
        self.assertEqual(health.state, "healthy")
        self.assertEqual(health.successes, 1)
        self.assertEqual(health.failures, 0)

        # After a failure, it immediately enters cooldown
        self.current_time += 5.0
        self.controller.record_failure("test_provider", "error")
        health = self.controller.health("test_provider")
        self.assertEqual(health.state, "cooldown")
        self.assertEqual(health.failures, 1)
        self.assertGreater(health.cooldown_remaining_seconds, 0)

        # Fast forward time to expire cooldown
        self.current_time += self.policy.failure_cooldown_seconds + 1.0
        health = self.controller.health("test_provider")
        # Now it should be degraded because last_failure_at > last_success_at, and cooldown is over
        self.assertEqual(health.state, "degraded")
        self.assertEqual(health.cooldown_remaining_seconds, 0)

        # Success clears failure streak
        self.controller.record_success("test_provider")
        health = self.controller.health("test_provider")
        self.assertEqual(health.state, "healthy")
        self.assertEqual(health.consecutive_failures, 0)

    def test_before_call_rate_limiting(self) -> None:
        # First call should be allowed without wait
        permit = self.controller.before_call("test_provider", "op", "query1")
        self.assertTrue(permit.allowed)
        self.assertEqual(permit.wait_seconds, 0.0)
        self.assertEqual(len(self.sleep_calls), 0)

        # Second call immediately should wait for minimum_interval_seconds
        permit = self.controller.before_call("test_provider", "op", "query2")
        self.assertTrue(permit.allowed)
        self.assertEqual(permit.wait_seconds, self.policy.minimum_interval_seconds)
        self.assertEqual(len(self.sleep_calls), 1)
        self.assertEqual(self.sleep_calls[0], self.policy.minimum_interval_seconds)

        # For the third call, let's fast forward time manually to simulate some time passing,
        # otherwise since next_call_at was bumped by minimum_interval_seconds *again*
        # (in the second call, wait_seconds was calculated, and then next_call_at = max(now, next_call_at) + min_interval)
        # Actually in second call:
        # wait_seconds = 1.0 (since next_call_at was now+1.0, and now didn't change before this)
        # next_call_at becomes (now+1.0) + 1.0 = now + 2.0
        # sleep(1.0) advances now by 1.0.
        # So in third call, now is now+1.0. next_call_at is now+2.0.
        # wait_seconds = 1.0.
        permit = self.controller.before_call("test_provider", "op", "query3")
        self.assertTrue(permit.allowed)
        self.assertEqual(permit.wait_seconds, self.policy.minimum_interval_seconds)

    def test_before_call_checkpoint(self) -> None:
        checkpoints: list[int] = []

        def mock_checkpoint() -> None:
            checkpoints.append(1)

        # Make a call that triggers a sleep
        self.controller.before_call("test_provider", "op", "query1")
        self.controller.before_call("test_provider", "op", "query2", checkpoint=mock_checkpoint)

        # checkpoint should be called twice if there's a sleep (before and after sleep)
        self.assertEqual(len(checkpoints), 2)

    def test_record_failure_exponential_backoff(self) -> None:
        # First failure -> base cooldown
        self.controller.record_failure("test_provider", "err1")
        health = self.controller.health("test_provider")
        self.assertEqual(health.cooldown_remaining_seconds, 10)

        # Second failure -> 2x base cooldown
        self.controller.record_failure("test_provider", "err2")
        health = self.controller.health("test_provider")
        self.assertEqual(health.cooldown_remaining_seconds, 20)

        # Third failure -> 4x base cooldown = 40
        self.controller.record_failure("test_provider", "err3")
        health = self.controller.health("test_provider")
        self.assertEqual(health.cooldown_remaining_seconds, 40)

        # Fourth failure -> 8x base cooldown = 80 -> capped at max_cooldown (60)
        self.controller.record_failure("test_provider", "err4")
        health = self.controller.health("test_provider")
        self.assertEqual(health.cooldown_remaining_seconds, 60)

    def test_record_no_result_negative_cache(self) -> None:
        self.controller.record_no_result("test_provider", "search", "query1")

        permit = self.controller.before_call("test_provider", "search", "query1")
        self.assertEqual(permit.availability, "negative_cache")
        self.assertFalse(permit.allowed)

        # Different query should be allowed
        permit = self.controller.before_call("test_provider", "search", "query2")
        self.assertEqual(permit.availability, "allowed")

        # After negative_cache_seconds has passed, the cache should expire
        self.current_time += self.policy.negative_cache_seconds + 1.0
        permit = self.controller.before_call("test_provider", "search", "query1")
        self.assertEqual(permit.availability, "allowed")

    def test_negative_cache_pruning(self) -> None:
        # Populate negative cache with more entries than maximum_negative_entries (5)
        # We need to simulate time passing so that entries have different expiration times.

        for i in range(7):
            self.controller.record_no_result("test_provider", "search", f"query{i}")
            self.current_time += 1.0

        # After recording 7, we should have exactly 5 items because of pruning.
        # But wait, cache is per-provider. Pruning happens in `record_no_result`.
        # When `record_no_result` is called, it inserts, then calls `_prune_negative_cache_locked(now)`.
        # In our setup, negative cache expiration is 30 seconds.
        # It prunes expired first. None are expired (we only advance by 1s each).
        # Then it drops entries based on expiration time.
        # The oldest entries (inserted first) have the earliest expiration time.
        # So it should keep the 5 most recent entries (query2 through query6).

        # Verify query0 and query1 are gone (pruned)
        permit = self.controller.before_call("test_provider", "search", "query0")
        self.assertEqual(permit.availability, "allowed")

        permit = self.controller.before_call("test_provider", "search", "query1")
        self.assertEqual(permit.availability, "allowed")

        # Verify query2 is still in negative cache
        permit = self.controller.before_call("test_provider", "search", "query2")
        self.assertEqual(permit.availability, "negative_cache")

        # Verify query6 is still in negative cache
        permit = self.controller.before_call("test_provider", "search", "query6")
        self.assertEqual(permit.availability, "negative_cache")

if __name__ == "__main__":
    unittest.main()
