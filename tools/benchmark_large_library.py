from __future__ import annotations

import argparse
import ctypes
import gc
import json
import math
import os
import platform
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from lightnovel_selector import (
    AppSettings,
    OperationCancelled,
    PersistentScanCache,
    RecognitionCorrectionMemory,
    ScanSession,
)
from lightnovel_selector.constants import SCAN_MAX_FILES

MIB = 1024 * 1024
BENCHMARK_SCHEMA_VERSION = 1
DATASET_BATCH_SIZE = 100
CANCEL_DELAY_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class PerformanceBudget:
    file_count: int
    max_cold_scan_seconds: float
    max_warm_scan_seconds: float
    max_warm_to_cold_ratio: float
    max_cancel_latency_seconds: float
    max_peak_working_set_mib: float
    min_warm_cache_reuse_ratio: float

    @classmethod
    def load(cls, path: Path) -> PerformanceBudget:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
            raise ValueError("性能预算版本无效。")

        file_count = _positive_integer(value.get("file_count"), "file_count")
        return cls(
            file_count=file_count,
            max_cold_scan_seconds=_positive_number(
                value.get("max_cold_scan_seconds"),
                "max_cold_scan_seconds",
            ),
            max_warm_scan_seconds=_positive_number(
                value.get("max_warm_scan_seconds"),
                "max_warm_scan_seconds",
            ),
            max_warm_to_cold_ratio=_ratio(
                value.get("max_warm_to_cold_ratio"),
                "max_warm_to_cold_ratio",
            ),
            max_cancel_latency_seconds=_positive_number(
                value.get("max_cancel_latency_seconds"),
                "max_cancel_latency_seconds",
            ),
            max_peak_working_set_mib=_positive_number(
                value.get("max_peak_working_set_mib"),
                "max_peak_working_set_mib",
            ),
            min_warm_cache_reuse_ratio=_ratio(
                value.get("min_warm_cache_reuse_ratio"),
                "min_warm_cache_reuse_ratio",
            ),
        )


@dataclass(frozen=True, slots=True)
class ScanMeasurement:
    seconds: float
    plan_count: int
    peak_working_set_mib: float | None
    working_set_growth_mib: float | None
    cache_stats: dict[str, int | str | None]


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    metric: str
    value: float
    comparison: str
    limit: float
    passed: bool


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"性能预算 {name} 必须是正整数。")
    return value


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"性能预算 {name} 必须是正数。")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"性能预算 {name} 必须是正数。")
    return result


def _ratio(value: object, name: str) -> float:
    result = _positive_number(value, name)
    if result > 1:
        raise ValueError(f"性能预算 {name} 必须在 0 到 1 之间。")
    return result


@lru_cache(maxsize=1)
def _windows_memory_functions() -> tuple[Any, Any]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)  # type: ignore[attr-defined]
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info = psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    get_process_memory_info.restype = ctypes.c_int
    return get_current_process, get_process_memory_info


def current_working_set_bytes() -> int | None:
    if os.name != "nt":
        return None
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process, get_process_memory_info = _windows_memory_functions()
    if not get_process_memory_info(
        get_current_process(),
        ctypes.byref(counters),
        counters.cb,
    ):
        return None
    return int(counters.WorkingSetSize)


class PeakWorkingSetSampler:
    def __init__(self, interval_seconds: float = 0.02) -> None:
        self.interval_seconds = interval_seconds
        self.baseline_bytes = current_working_set_bytes()
        self.peak_bytes = self.baseline_bytes
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> PeakWorkingSetSampler:  # noqa: PYI034
        if self.baseline_bytes is not None:
            self._thread = threading.Thread(
                target=self._sample,
                name="performance-memory-sampler",
                daemon=True,
            )
            self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc_value, traceback
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._record_sample()

    def _record_sample(self) -> None:
        current = current_working_set_bytes()
        if current is not None and (self.peak_bytes is None or current > self.peak_bytes):
            self.peak_bytes = current

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._record_sample()

    @property
    def peak_mib(self) -> float | None:
        return None if self.peak_bytes is None else self.peak_bytes / MIB

    @property
    def growth_mib(self) -> float | None:
        if self.baseline_bytes is None or self.peak_bytes is None:
            return None
        return max(0, self.peak_bytes - self.baseline_bytes) / MIB


def create_dataset(root: Path, file_count: int) -> float:
    started = time.perf_counter()
    active_batch = -1
    batch_dir = root
    for index in range(file_count):
        batch = index // DATASET_BATCH_SIZE
        if batch != active_batch:
            batch_dir = root / f"batch-{batch:03d}"
            batch_dir.mkdir()
            active_batch = batch
        series = index // 20
        volume = index % 20 + 1
        path = batch_dir / f"Series {series:04d} Vol {volume:02d} - {index:05d}.txt"
        path.write_text(
            f"Title: Series {series:04d} Volume {volume:02d}\nUnique: {index:05d}\n",
            encoding="utf-8",
        )
    return time.perf_counter() - started


def _new_session(
    root: Path,
    cache_path: Path,
    aliases: RecognitionCorrectionMemory,
    cancel_event: threading.Event,
) -> ScanSession:
    return ScanSession(
        root,
        AppSettings(use_network=False, recursive=True),
        metadata_providers=(),
        correction_memory=aliases,
        cancel_event=cancel_event,
        scan_cache_factory=lambda: PersistentScanCache(cache_path),
    )


def measure_cancellation(
    root: Path,
    cache_path: Path,
    aliases: RecognitionCorrectionMemory,
) -> float:
    cancel_event = threading.Event()
    requested_at: list[float] = []

    def request_cancel() -> None:
        time.sleep(CANCEL_DELAY_SECONDS)
        requested_at.append(time.perf_counter())
        cancel_event.set()

    timer = threading.Thread(target=request_cancel, name="performance-cancel", daemon=True)
    timer.start()
    cancelled_at: float | None = None
    try:
        _new_session(root, cache_path, aliases, cancel_event).run()
    except OperationCancelled:
        cancelled_at = time.perf_counter()
    finally:
        timer.join(timeout=1)

    if cancelled_at is None or not requested_at:
        raise RuntimeError("基准扫描未能在完成前触发取消。")
    cache_path.unlink(missing_ok=True)
    return max(0.0, cancelled_at - requested_at[0])


def measure_scan(
    root: Path,
    cache_path: Path,
    aliases: RecognitionCorrectionMemory,
) -> ScanMeasurement:
    session = _new_session(root, cache_path, aliases, threading.Event())
    with PeakWorkingSetSampler() as memory:
        started = time.perf_counter()
        result = session.run()
        elapsed = time.perf_counter() - started
    return ScanMeasurement(
        seconds=elapsed,
        plan_count=len(result.plans),
        peak_working_set_mib=memory.peak_mib,
        working_set_growth_mib=memory.growth_mib,
        cache_stats=result.cache_stats.to_dict(),
    )


def evaluate_budget(
    budget: PerformanceBudget,
    *,
    file_count: int,
    cancellation_seconds: float,
    cold: ScanMeasurement,
    warm: ScanMeasurement,
) -> list[BudgetCheck]:
    warm_ratio = warm.seconds / cold.seconds if cold.seconds else math.inf
    reused = warm.cache_stats.get("reused_files")
    reuse_ratio = int(reused or 0) / file_count if file_count else 0.0
    peak_values = [value for value in (cold.peak_working_set_mib, warm.peak_working_set_mib) if value is not None]
    peak_mib = max(peak_values, default=0.0)
    return [
        BudgetCheck("file_count", float(file_count), "==", float(budget.file_count), file_count == budget.file_count),
        BudgetCheck(
            "cold_scan_seconds",
            cold.seconds,
            "<=",
            budget.max_cold_scan_seconds,
            cold.seconds <= budget.max_cold_scan_seconds,
        ),
        BudgetCheck(
            "warm_scan_seconds",
            warm.seconds,
            "<=",
            budget.max_warm_scan_seconds,
            warm.seconds <= budget.max_warm_scan_seconds,
        ),
        BudgetCheck(
            "warm_to_cold_ratio",
            warm_ratio,
            "<=",
            budget.max_warm_to_cold_ratio,
            warm_ratio <= budget.max_warm_to_cold_ratio,
        ),
        BudgetCheck(
            "cancel_latency_seconds",
            cancellation_seconds,
            "<=",
            budget.max_cancel_latency_seconds,
            cancellation_seconds <= budget.max_cancel_latency_seconds,
        ),
        BudgetCheck(
            "peak_working_set_mib",
            peak_mib,
            "<=",
            budget.max_peak_working_set_mib,
            not peak_values or peak_mib <= budget.max_peak_working_set_mib,
        ),
        BudgetCheck(
            "warm_cache_reuse_ratio",
            reuse_ratio,
            ">=",
            budget.min_warm_cache_reuse_ratio,
            reuse_ratio >= budget.min_warm_cache_reuse_ratio,
        ),
        BudgetCheck(
            "cold_plan_count",
            float(cold.plan_count),
            "==",
            float(file_count),
            cold.plan_count == file_count,
        ),
        BudgetCheck(
            "warm_plan_count",
            float(warm.plan_count),
            "==",
            float(file_count),
            warm.plan_count == file_count,
        ),
    ]


def _write_github_summary(report: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    measurements = report["measurements"]
    cold = measurements["cold_scan"]
    warm = measurements["warm_scan"]
    lines = [
        "## 1 万文件性能基准",
        "",
        "| 指标 | 结果 |",
        "| --- | ---: |",
        f"| 冷缓存扫描 | {cold['seconds']:.2f} 秒 |",
        f"| 热缓存扫描 | {warm['seconds']:.2f} 秒 |",
        f"| 取消响应 | {measurements['cancel_latency_seconds']:.3f} 秒 |",
        f"| 峰值工作集 | {measurements['peak_working_set_mib']:.1f} MiB |",
        f"| 热缓存复用率 | {measurements['warm_cache_reuse_ratio']:.1%} |",
        f"| 性能预算 | {'通过' if report['passed'] else '失败'} |",
        "",
    ]
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines))


def run_benchmark(file_count: int, budget: PerformanceBudget) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="lightnovel-selector-benchmark-") as temp_dir:
        base = Path(temp_dir)
        library = base / "library"
        library.mkdir()
        dataset_seconds = create_dataset(library, file_count)
        aliases = RecognitionCorrectionMemory(base / "aliases.json")
        cache_path = base / "scan-cache.json"
        cancellation_seconds = measure_cancellation(
            library,
            base / "cancel-cache.json",
            aliases,
        )
        cold = measure_scan(library, cache_path, aliases)
        gc.collect()
        warm = measure_scan(library, cache_path, aliases)
        cache_bytes = cache_path.stat().st_size

    checks = evaluate_budget(
        budget,
        file_count=file_count,
        cancellation_seconds=cancellation_seconds,
        cold=cold,
        warm=warm,
    )
    warm_ratio = warm.seconds / cold.seconds if cold.seconds else math.inf
    reused = int(warm.cache_stats.get("reused_files") or 0)
    peak_mib = max(
        (value for value in (cold.peak_working_set_mib, warm.peak_working_set_mib) if value is not None),
        default=0.0,
    )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "recorded_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "system": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
        },
        "workload": {
            "file_count": file_count,
            "recursive": True,
            "network": False,
            "file_type": "txt",
        },
        "measurements": {
            "dataset_creation_seconds": dataset_seconds,
            "cancel_latency_seconds": cancellation_seconds,
            "cold_scan": asdict(cold),
            "warm_scan": asdict(warm),
            "warm_to_cold_ratio": warm_ratio,
            "warm_cache_reuse_ratio": reused / file_count if file_count else 0.0,
            "peak_working_set_mib": peak_mib,
            "cache_file_bytes": cache_bytes,
        },
        "budget": asdict(budget),
        "checks": [asdict(check) for check in checks],
        "passed": all(check.passed for check in checks),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 LightNovelSelector 大型书库性能基准。")
    parser.add_argument("--files", type=int, default=10_000, help="生成的小说文件数量。")
    parser.add_argument(
        "--budget",
        type=Path,
        default=Path("benchmarks/performance_budget.json"),
        help="性能预算 JSON 路径。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/performance/large-library.json"),
        help="机器可读结果输出路径。",
    )
    parser.add_argument("--enforce", action="store_true", help="预算未通过时返回非零退出码。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.files <= 0 or args.files > SCAN_MAX_FILES:
        raise ValueError(f"性能基准文件数必须在 1 到 {SCAN_MAX_FILES} 之间。")
    budget = PerformanceBudget.load(args.budget)
    report = run_benchmark(args.files, budget)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_github_summary(report)

    measurements = report["measurements"]
    print(
        "性能基准："
        f"冷扫描 {measurements['cold_scan']['seconds']:.2f}s，"
        f"热扫描 {measurements['warm_scan']['seconds']:.2f}s，"
        f"取消响应 {measurements['cancel_latency_seconds']:.3f}s，"
        f"峰值工作集 {measurements['peak_working_set_mib']:.1f} MiB。"
    )
    print(f"结果：{'通过' if report['passed'] else '未通过'}；报告：{args.output}")
    return 0 if report["passed"] or not args.enforce else 2


if __name__ == "__main__":
    raise SystemExit(main())
