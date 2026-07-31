import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lightnovel_selector import (
    AniListProvider,
    AppSettings,
    BookIdentity,
    BookMetadata,
    JikanProvider,
    MetadataProvider,
    MetadataProviderRegistry,
    MetadataProviderSetting,
    PersistentMetadataCache,
    ProviderReliabilityController,
    ProviderReliabilityPolicy,
    ResolveResult,
    SeriesResolver,
    app_settings_from_dict,
    app_settings_to_dict,
    build_classification_plan,
    builtin_metadata_providers,
    normalize_for_match,
    resolve_result_to_dict,
)
from lightnovel_selector.application import ApplicationService


class StubProvider(MetadataProvider):
    provider_id = "stub"
    display_name = "Stub"

    def __init__(
        self,
        *,
        provider_id: str = "stub",
        display_name: str = "Stub",
        priority: int = 100,
        cache_version: str = "1",
        series_result: ResolveResult | None = None,
        book_result: BookMetadata | None = None,
        series_error: Exception | None = None,
        book_error: Exception | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.priority = priority
        self.cache_version = cache_version
        self.series_result = series_result
        self.book_result = book_result
        self.series_error = series_error
        self.book_error = book_error
        self.series_calls = 0
        self.book_calls = 0

    def resolve_series(
        self,
        query: str,
        *,
        timeout: float,
    ) -> ResolveResult | None:
        self.series_calls += 1
        if self.series_error is not None:
            raise self.series_error
        return self.series_result

    def resolve_book(
        self,
        query: str,
        *,
        series_name: str,
        timeout: float,
    ) -> BookMetadata | None:
        self.book_calls += 1
        if self.book_error is not None:
            raise self.book_error
        return self.book_result


class BrokenStringError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("broken string conversion")


class FakeClock:
    def __init__(self) -> None:
        self.current = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds

    def advance(self, seconds: float) -> None:
        self.current += seconds


def series_result(
    series_name: str,
    *,
    source: str = "untrusted",
    confidence: float = 0.9,
) -> ResolveResult:
    return ResolveResult(
        identity=BookIdentity(title=series_name, series_name=series_name),
        source=source,
        confidence=confidence,
        local_guess=series_name,
    )


class MetadataProviderRegistryTests(unittest.TestCase):
    def test_registry_orders_by_priority_and_keeps_stable_ties(self) -> None:
        late = StubProvider(provider_id="late", display_name="Late", priority=30)
        first = StubProvider(provider_id="first", display_name="First", priority=10)
        tied = StubProvider(provider_id="tied", display_name="Tied", priority=10)

        registry = MetadataProviderRegistry((late, first, tied))

        self.assertEqual(
            [provider.provider_id for provider in registry],
            ["first", "tied", "late"],
        )

    def test_registry_rejects_duplicate_or_invalid_descriptors(self) -> None:
        with self.assertRaisesRegex(ValueError, "ID 重复"):
            MetadataProviderRegistry(
                (
                    StubProvider(provider_id="same"),
                    StubProvider(provider_id="same"),
                )
            )
        with self.assertRaisesRegex(ValueError, "ID 必须"):
            MetadataProviderRegistry((StubProvider(provider_id="../unsafe"),))
        with self.assertRaisesRegex(TypeError, "必须继承"):
            MetadataProviderRegistry((object(),))  # type: ignore[arg-type]

    def test_cache_namespace_changes_with_provider_version(self) -> None:
        first = MetadataProviderRegistry((StubProvider(provider_id="demo", cache_version="1"),))
        second = MetadataProviderRegistry((StubProvider(provider_id="demo", cache_version="2"),))

        self.assertNotEqual(first.cache_namespace, second.cache_namespace)

    def test_default_registry_is_explicit_and_deterministic(self) -> None:
        providers = builtin_metadata_providers()

        self.assertEqual(
            [provider.provider_id for provider in providers],
            ["bangumi", "anilist", "jikan"],
        )

    def test_registry_applies_enabled_state_and_user_priority(self) -> None:
        first = StubProvider(provider_id="first", priority=10)
        second = StubProvider(provider_id="second", priority=20)
        third = StubProvider(provider_id="third", priority=30)
        registry = MetadataProviderRegistry((first, second, third))

        configured = registry.configured(
            (
                MetadataProviderSetting("first", enabled=False, priority=10),
                MetadataProviderSetting("third", enabled=True, priority=5),
            )
        )

        self.assertEqual(
            [provider.provider_id for provider in configured],
            ["third", "second"],
        )
        self.assertEqual(configured.effective_priority("third"), 5)
        self.assertIsNone(configured.get("first"))
        self.assertNotEqual(configured.cache_namespace, registry.cache_namespace)

        reconfigured = configured.configured(
            (
                MetadataProviderSetting("first", enabled=True, priority=1),
                MetadataProviderSetting("third", enabled=False, priority=30),
            )
        )
        self.assertEqual(
            [provider.provider_id for provider in reconfigured],
            ["first", "second"],
        )

    def test_registry_rejects_duplicate_or_invalid_settings(self) -> None:
        registry = MetadataProviderRegistry((StubProvider(provider_id="demo"),))

        with self.assertRaisesRegex(ValueError, "设置 ID 重复"):
            registry.configured(
                (
                    MetadataProviderSetting("demo"),
                    MetadataProviderSetting("demo"),
                )
            )
        with self.assertRaisesRegex(ValueError, "优先级"):
            registry.configured((MetadataProviderSetting("demo", priority=1001),))


class ProviderReliabilityTests(unittest.TestCase):
    @staticmethod
    def controller(
        clock: FakeClock,
        *,
        interval: float = 0.0,
        cooldown: float = 10.0,
        negative_ttl: float = 5.0,
    ) -> ProviderReliabilityController:
        return ProviderReliabilityController(
            ProviderReliabilityPolicy(
                minimum_interval_seconds=interval,
                failure_cooldown_seconds=cooldown,
                maximum_cooldown_seconds=60.0,
                negative_cache_seconds=negative_ttl,
            ),
            monotonic=clock,
            sleep=clock.sleep,
        )

    def test_rate_limit_reserves_calls_per_provider(self) -> None:
        clock = FakeClock()
        controller = self.controller(clock, interval=1.0)

        first = controller.before_call("demo", "series", "First")
        controller.record_success("demo")
        second = controller.before_call("demo", "series", "Second")

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertEqual(second.wait_seconds, 1.0)
        self.assertEqual(clock.sleeps, [1.0])
        health = controller.health("demo")
        self.assertEqual(health.attempts, 2)
        self.assertEqual(health.rate_limit_waits, 1)
        self.assertEqual(health.state, "healthy")

    def test_failure_enters_exponential_cooldown_until_success(self) -> None:
        clock = FakeClock()
        controller = self.controller(clock, cooldown=10.0)

        self.assertTrue(controller.before_call("demo", "series", "One").allowed)
        controller.record_failure("demo", "offline")
        self.assertEqual(
            controller.before_call("demo", "series", "Two").availability,
            "cooldown",
        )
        self.assertEqual(controller.health("demo").cooldown_remaining_seconds, 10)

        clock.advance(10.0)
        self.assertTrue(controller.before_call("demo", "series", "Two").allowed)
        controller.record_failure("demo", "still offline")
        self.assertEqual(controller.health("demo").cooldown_remaining_seconds, 20)

        clock.advance(20.0)
        self.assertTrue(controller.before_call("demo", "series", "Three").allowed)
        controller.record_success("demo")
        self.assertEqual(controller.health("demo").state, "healthy")
        self.assertEqual(controller.health("demo").consecutive_failures, 0)

    def test_only_clean_no_result_enters_short_negative_cache(self) -> None:
        clock = FakeClock()
        controller = self.controller(clock, negative_ttl=5.0)

        self.assertTrue(controller.before_call("demo", "series", "Missing").allowed)
        controller.record_no_result("demo", "series", "Missing")
        self.assertEqual(
            controller.before_call("demo", "series", "Missing").availability,
            "negative_cache",
        )
        self.assertTrue(controller.before_call("demo", "book", "Missing").allowed)
        clock.advance(6.0)
        self.assertTrue(controller.before_call("demo", "series", "Missing").allowed)
        self.assertEqual(controller.health("demo").negative_cache_hits, 1)

    def test_resolver_skips_failed_source_but_keeps_later_source(self) -> None:
        clock = FakeClock()
        controller = self.controller(clock, cooldown=30.0)
        broken = StubProvider(
            provider_id="broken",
            display_name="损坏来源",
            priority=10,
            series_error=RuntimeError("offline"),
        )
        healthy = StubProvider(
            provider_id="healthy",
            display_name="可用来源",
            priority=20,
            series_result=series_result("Healthy Series"),
        )
        with TemporaryDirectory() as temp_dir:
            cache = PersistentMetadataCache(Path(temp_dir) / "metadata.json")
            first = SeriesResolver(
                persistent_cache=cache,
                providers=(broken, healthy),
                reliability=controller,
            )
            second = SeriesResolver(
                persistent_cache=cache,
                providers=(broken, healthy),
                reliability=controller,
            )

            self.assertEqual(first.resolve("First.epub").series_name, "Healthy Series")
            self.assertEqual(second.resolve("Second.epub").series_name, "Healthy Series")

        self.assertEqual(broken.series_calls, 1)
        self.assertEqual(healthy.series_calls, 2)
        self.assertIn("暂时冷却", second.last_network_error or "")

    def test_candidate_lookup_reuses_negative_cache_without_hiding_successes(self) -> None:
        clock = FakeClock()
        controller = self.controller(clock)
        missing = StubProvider(provider_id="missing", priority=10)
        healthy = StubProvider(
            provider_id="healthy",
            priority=20,
            series_result=series_result("Candidate"),
        )
        with TemporaryDirectory() as temp_dir:
            resolver = SeriesResolver(
                persistent_cache=PersistentMetadataCache(Path(temp_dir) / "metadata.json"),
                providers=(missing, healthy),
                reliability=controller,
            )

            self.assertEqual(len(resolver.resolve_candidates("Demo")), 1)
            self.assertEqual(len(resolver.resolve_candidates("Demo")), 1)

        self.assertEqual(missing.series_calls, 1)
        self.assertEqual(healthy.series_calls, 2)
        self.assertEqual(controller.health("missing").negative_cache_hits, 1)

    def test_health_error_does_not_retain_the_current_query(self) -> None:
        clock = FakeClock()
        controller = self.controller(clock)
        provider = StubProvider(
            provider_id="broken",
            series_error=RuntimeError("request Demo Novel or Demo%20Novel failed"),
        )
        with TemporaryDirectory() as temp_dir:
            resolver = SeriesResolver(
                persistent_cache=PersistentMetadataCache(Path(temp_dir) / "metadata.json"),
                providers=(provider,),
                reliability=controller,
            )
            resolver.resolve_candidates("Demo Novel")

        error = controller.health("broken").last_error or ""
        self.assertNotIn("Demo Novel", error)
        self.assertNotIn("Demo%20Novel", error)
        self.assertIn("<当前查询>", error)


class ProviderSettingsStorageTests(unittest.TestCase):
    def test_provider_settings_round_trip_and_ignore_invalid_entries(self) -> None:
        settings = AppSettings(
            provider_settings=(
                MetadataProviderSetting("bangumi", enabled=False, priority=20),
                MetadataProviderSetting("anilist", enabled=True, priority=5),
            )
        )

        self.assertEqual(app_settings_from_dict(app_settings_to_dict(settings)), settings)
        loaded = app_settings_from_dict(
            {
                "provider_settings": [
                    {"provider_id": "../bad", "enabled": True, "priority": 1},
                    {"provider_id": "bangumi", "enabled": "yes", "priority": 1},
                    {"provider_id": "anilist", "enabled": True, "priority": 1001},
                    {"provider_id": "jikan", "enabled": True, "priority": 30},
                ]
            }
        )
        self.assertEqual(
            loaded.provider_settings,
            (MetadataProviderSetting("jikan", enabled=True, priority=30),),
        )


class SeriesResolverProviderTests(unittest.TestCase):
    temp_dir: TemporaryDirectory[str]
    cache: PersistentMetadataCache

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache = PersistentMetadataCache(Path(self.temp_dir.name) / "metadata.json")

    def test_custom_provider_can_resolve_without_core_changes(self) -> None:
        provider = StubProvider(
            provider_id="community-library",
            display_name="社区书库",
            series_result=ResolveResult(
                identity=BookIdentity(
                    title="  Demo   Novel  ",
                    series_name="Demo:Novel",
                    authors=("Author",),
                    language="EN_us",
                    tags=("Fantasy",),
                ),
                source="伪造来源",
                confidence=0.87,
                local_guess="wrong",
                metadata_cover_url="http://unsafe.example/cover.jpg",
            ),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(provider,),
        )

        result = resolver.resolve("Demo Novel.epub")

        self.assertEqual(result.source, "社区书库")
        self.assertEqual(result.series_name, "Demo_Novel")
        self.assertEqual(result.identity.title, "Demo Novel")
        self.assertEqual(result.identity.language, "en")
        self.assertIsNone(result.metadata_cover_url)

    def test_unexpected_provider_failure_does_not_block_later_provider(self) -> None:
        broken = StubProvider(
            provider_id="broken",
            display_name="损坏来源",
            priority=10,
            series_error=AssertionError("provider bug"),
        )
        healthy = StubProvider(
            provider_id="healthy",
            display_name="可用来源",
            priority=20,
            series_result=series_result("Healthy Series"),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(broken, healthy),
        )

        result = resolver.resolve("Healthy Series.epub")

        self.assertEqual(result.source, "可用来源")
        self.assertEqual(result.series_name, "Healthy Series")
        self.assertIn("损坏来源", resolver.last_network_error or "")
        self.assertIn("provider bug", resolver.last_network_error or "")

    def test_invalid_provider_result_is_isolated(self) -> None:
        invalid = StubProvider(
            provider_id="invalid",
            display_name="非法来源",
            priority=10,
            series_result=series_result("Invalid", confidence=math.nan),
        )
        healthy = StubProvider(
            provider_id="healthy",
            display_name="可用来源",
            priority=20,
            series_result=series_result("Valid"),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(invalid, healthy),
        )

        result = resolver.resolve("Valid.epub")

        self.assertEqual(result.series_name, "Valid")
        self.assertIn("有限数字", resolver.last_network_error or "")

    def test_out_of_range_provider_volume_is_isolated(self) -> None:
        invalid = StubProvider(
            provider_id="invalid",
            display_name="非法来源",
            priority=10,
            series_result=ResolveResult(
                identity=BookIdentity(
                    title="Invalid",
                    series_name="Invalid",
                    volume_number=1000,
                ),
                source="invalid",
                confidence=0.8,
                local_guess="Invalid",
            ),
        )
        healthy = StubProvider(
            provider_id="healthy",
            display_name="可用来源",
            priority=20,
            series_result=series_result("Valid"),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(invalid, healthy),
        )

        result = resolver.resolve("Valid.epub")

        self.assertEqual(result.series_name, "Valid")
        self.assertIn("卷号", resolver.last_network_error or "")

    def test_broken_exception_string_is_safely_reported(self) -> None:
        broken = StubProvider(
            provider_id="broken",
            display_name="损坏来源",
            priority=10,
            series_error=BrokenStringError(),
        )
        healthy = StubProvider(
            provider_id="healthy",
            display_name="可用来源",
            priority=20,
            series_result=series_result("Valid"),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(broken, healthy),
        )

        result = resolver.resolve("Valid.epub")

        self.assertEqual(result.series_name, "Valid")
        self.assertIn("BrokenStringError", resolver.last_network_error or "")

    def test_memory_error_is_not_hidden_by_provider_boundary(self) -> None:
        provider = StubProvider(
            provider_id="memory",
            display_name="内存测试",
            series_error=MemoryError("out"),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(provider,),
        )

        with self.assertRaises(MemoryError):
            resolver.resolve("Demo.epub")

    def test_book_metadata_falls_back_and_sanitizes_urls(self) -> None:
        broken = StubProvider(
            provider_id="broken",
            display_name="损坏来源",
            priority=10,
            book_error=RuntimeError("offline"),
        )
        healthy = StubProvider(
            provider_id="healthy",
            display_name="详情来源",
            priority=20,
            book_result=BookMetadata(
                identity=BookIdentity(title="Demo 03", series_name="Demo"),
                source="spoofed",
                confidence=0.93,
                query="wrong",
                summary=" A\n\nB ",
                cover_url="http://unsafe.example/cover.jpg",
                url="https://example.test/book/3",
            ),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(broken, healthy),
        )

        metadata = resolver.resolve_book_metadata_for_query("Demo 03")

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.source, "详情来源")
        self.assertEqual(metadata.query, "Demo 03")
        self.assertEqual(metadata.summary, "A\nB")
        self.assertIsNone(metadata.cover_url)
        self.assertEqual(metadata.url, "https://example.test/book/3")
        self.assertIn("offline", resolver.last_network_error or "")

    def test_persistent_cache_is_partitioned_by_provider_set(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = PersistentMetadataCache(Path(temp_dir) / "metadata.json")
            first_provider = StubProvider(
                provider_id="first",
                display_name="第一来源",
                series_result=series_result("First Series"),
            )
            first = SeriesResolver(
                use_network=True,
                persistent_cache=cache,
                providers=(first_provider,),
            )
            self.assertEqual(first.resolve("Demo.epub").series_name, "First Series")

            second_provider = StubProvider(
                provider_id="second",
                display_name="第二来源",
                series_result=series_result("Second Series"),
            )
            second = SeriesResolver(
                use_network=True,
                persistent_cache=cache,
                providers=(second_provider,),
            )

            self.assertEqual(second.resolve("Demo.epub").series_name, "Second Series")
            self.assertEqual(second_provider.series_calls, 1)

    def test_cached_result_is_bound_to_registered_provider_and_revalidated(self) -> None:
        provider = StubProvider(
            provider_id="trusted",
            display_name="可信来源",
            series_result=series_result("Live Series"),
        )
        registry = MetadataProviderRegistry((provider,))
        cache_key = f"series:{registry.cache_namespace}:{normalize_for_match('Demo')}"
        cached = resolve_result_to_dict(
            ResolveResult(
                identity=BookIdentity(title="Cached", series_name="Cached"),
                source="伪造来源",
                confidence=0.8,
                local_guess="wrong",
                metadata_cover_url="http://unsafe.example/cover.jpg",
            )
        )
        cached["_provider_id"] = "trusted"
        self.cache.set(cache_key, cached)
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=registry,
        )

        result = resolver.resolve("Demo.epub")

        self.assertEqual(result.source, "可信来源")
        self.assertEqual(result.local_guess, "Demo")
        self.assertIsNone(result.metadata_cover_url)
        self.assertEqual(provider.series_calls, 0)

    def test_cached_result_from_unknown_provider_is_ignored(self) -> None:
        provider = StubProvider(
            provider_id="trusted",
            display_name="可信来源",
            series_result=series_result("Live Series"),
        )
        registry = MetadataProviderRegistry((provider,))
        cache_key = f"series:{registry.cache_namespace}:{normalize_for_match('Demo')}"
        cached = resolve_result_to_dict(series_result("Poisoned Series"))
        cached["_provider_id"] = "removed-provider"
        self.cache.set(cache_key, cached)
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=registry,
        )

        result = resolver.resolve("Demo.epub")

        self.assertEqual(result.series_name, "Live Series")
        self.assertEqual(provider.series_calls, 1)

    def test_memory_cache_hit_clears_previous_provider_warning(self) -> None:
        broken = StubProvider(
            provider_id="broken",
            display_name="损坏来源",
            priority=10,
            series_error=RuntimeError("offline"),
        )
        healthy = StubProvider(
            provider_id="healthy",
            display_name="可用来源",
            priority=20,
            series_result=series_result("Healthy Series"),
        )
        resolver = SeriesResolver(
            use_network=True,
            persistent_cache=self.cache,
            providers=(broken, healthy),
        )

        resolver.resolve("Demo.epub")
        self.assertIn("offline", resolver.last_network_error or "")

        resolver.resolve("Demo.epub")

        self.assertIsNone(resolver.last_network_error)
        self.assertEqual(broken.series_calls, 1)

    def test_classification_plan_accepts_injected_provider_registry(self) -> None:
        provider = StubProvider(
            provider_id="community",
            display_name="社区书库",
            series_result=series_result("Community Series"),
        )
        registry = MetadataProviderRegistry((provider,))
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Demo Vol.01.txt").write_text("chapter", encoding="utf-8")

            plans = build_classification_plan(
                root,
                use_network=True,
                metadata_providers=registry,
            )

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].series_name, "Community Series")
        self.assertEqual(plans[0].resolver_source, "社区书库")

    def test_application_snapshot_reports_injected_providers(self) -> None:
        provider = StubProvider(
            provider_id="community",
            display_name="社区书库",
            priority=42,
        )
        service = ApplicationService(metadata_providers=(provider,))

        snapshot = service.snapshot()["metadata_providers"]

        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]["id"], "community")
        self.assertEqual(snapshot[0]["name"], "社区书库")
        self.assertEqual(snapshot[0]["priority"], 42)
        self.assertTrue(snapshot[0]["enabled"])
        self.assertEqual(snapshot[0]["status"], "idle")

        service.provider_reliability.before_call("community", "series", "Demo")
        service.provider_reliability.record_failure("community", "社区书库: offline")
        health = service.snapshot()["metadata_providers"][0]
        self.assertEqual(health["status"], "cooldown")
        self.assertGreater(health["cooldown_remaining_seconds"], 0)
        self.assertEqual(health["last_error"], "社区书库: offline")

    def test_application_saves_provider_order_and_disabled_state(self) -> None:
        first = StubProvider(provider_id="first", display_name="第一来源", priority=10)
        second = StubProvider(provider_id="second", display_name="第二来源", priority=20)
        with (
            patch("lightnovel_selector.application.load_app_settings", return_value=AppSettings()),
            patch("lightnovel_selector.application.try_save_app_settings", return_value=None),
        ):
            service = ApplicationService(metadata_providers=(first, second))
            result = service.save_settings(
                {
                    "use_network": True,
                    "recursive": False,
                    "auto_rename": False,
                    "custom_rules": [],
                    "provider_settings": [
                        {"provider_id": "first", "enabled": False, "priority": 10},
                        {"provider_id": "second", "enabled": True, "priority": 5},
                    ],
                }
            )

        self.assertTrue(result["saved"])
        self.assertEqual(
            service.settings.provider_settings,
            (
                MetadataProviderSetting("first", enabled=False, priority=10),
                MetadataProviderSetting("second", enabled=True, priority=5),
            ),
        )
        snapshot = result["state"]["metadata_providers"]
        self.assertEqual([item["id"] for item in snapshot], ["second", "first"])
        self.assertEqual(snapshot[1]["status"], "disabled")

    def test_all_disabled_providers_fall_back_to_local_without_calls(self) -> None:
        provider = StubProvider(
            provider_id="remote",
            series_result=series_result("Remote Series"),
        )
        registry = MetadataProviderRegistry((provider,)).configured(
            (MetadataProviderSetting("remote", enabled=False, priority=10),)
        )
        resolver = SeriesResolver(
            persistent_cache=self.cache,
            providers=registry,
        )

        result = resolver.resolve("Local.Series.Vol.01.epub")

        self.assertEqual(result.series_name, "Local Series")
        self.assertEqual(provider.series_calls, 0)


class BuiltinProviderMappingTests(unittest.TestCase):
    def test_anilist_maps_book_metadata(self) -> None:
        payload = {
            "data": {
                "Page": {
                    "media": [
                        {
                            "title": {
                                "english": "Demo Novel",
                                "romaji": "Demo",
                                "native": "デモ",
                            },
                            "synonyms": [],
                            "genres": ["Fantasy"],
                            "description": "Line one\n\nLine two",
                            "siteUrl": "https://anilist.co/manga/1",
                            "countryOfOrigin": "JP",
                            "coverImage": {"large": "https://example.test/anilist.jpg"},
                            "staff": {
                                "edges": [
                                    {
                                        "role": "Story",
                                        "node": {
                                            "name": {
                                                "full": "Example Author",
                                                "native": None,
                                            }
                                        },
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        }
        with patch(
            "lightnovel_selector.providers.anilist.http_json",
            return_value=payload,
        ):
            metadata = AniListProvider().resolve_book(
                "Demo Novel",
                series_name="Demo Novel",
                timeout=1,
            )

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.identity.authors, ("Example Author",))
        self.assertEqual(metadata.identity.language, "ja")
        self.assertEqual(metadata.identity.tags, ("Fantasy",))
        self.assertEqual(metadata.summary, "Line one\nLine two")

    def test_jikan_maps_book_metadata(self) -> None:
        payload = {
            "data": [
                {
                    "title_english": "Demo Novel",
                    "title": "Demo",
                    "title_japanese": "デモ",
                    "titles": [],
                    "authors": [{"name": "Example Author"}],
                    "genres": [{"name": "Fantasy"}],
                    "themes": [],
                    "demographics": [],
                    "synopsis": "Summary",
                    "url": "https://myanimelist.net/manga/1",
                    "images": {"jpg": {"large_image_url": "https://example.test/jikan.jpg"}},
                }
            ]
        }
        with patch(
            "lightnovel_selector.providers.jikan.http_json",
            return_value=payload,
        ):
            metadata = JikanProvider().resolve_book(
                "Demo Novel",
                series_name="Demo Novel",
                timeout=1,
            )

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.identity.authors, ("Example Author",))
        self.assertEqual(metadata.identity.tags, ("Fantasy",))
        self.assertEqual(metadata.cover_url, "https://example.test/jikan.jpg")


if __name__ == "__main__":
    unittest.main()
