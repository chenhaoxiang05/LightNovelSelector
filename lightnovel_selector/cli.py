from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from pathlib import Path

from .classification import (
    build_classification_plan,
    execute_classification_plan,
    plan_status_label,
    undo_classification_report,
)
from .constants import REPORT_FILE_NAME
from .corrections import RecognitionCorrectionMemory
from .models import ClassificationPlan
from .scan_cache import PersistentScanCache
from .storage import load_app_settings


def print_plan(plans: list[ClassificationPlan]) -> None:
    if not plans:
        print("没有找到可分类的小说文件。")
        return
    for plan in plans:
        marker = "MOVE" if plan.will_move else "SKIP"
        note = f"\t{plan.note}" if plan.note else ""
        print(
            f"{marker}\t{plan.source_path.name}\t=>\t{plan.target_dir.name}\\{plan.target_path.name}"
            f"\t[{plan.resolver_source}, {plan.confidence:.0%} {plan.confidence_level}, "
            f"{plan_status_label(plan.status)}]\t{plan.classification_reason}{note}"
        )


def run_cli(args: argparse.Namespace) -> int:
    root = Path(args.folder)
    settings = load_app_settings()
    scan_cache: PersistentScanCache | None = None
    correction_memory = RecognitionCorrectionMemory()
    cache_warning: str | None = None
    try:
        scan_cache = PersistentScanCache()
    except OSError as exc:
        cache_warning = str(exc)[:2000]
    with scan_cache if scan_cache is not None else nullcontext():
        plans = build_classification_plan(
            root,
            recursive=args.recursive,
            use_network=not args.no_network,
            auto_rename=args.auto_rename,
            custom_rules=settings.custom_rules,
            progress=None if args.quiet else print,
            scan_cache=scan_cache,
            correction_memory=correction_memory,
        )
    if scan_cache is not None:
        cache_stats = scan_cache.stats
        cache_warning = cache_stats.write_warning
        if not args.quiet and cache_stats.reused_files:
            print(f"增量扫描：复用了 {cache_stats.reused_files} 个未变化文件的缓存。")
    if cache_warning:
        print(f"警告：扫描缓存不可用，本次结果不受影响：{cache_warning}", file=sys.stderr)
    print_plan(plans)
    if args.dry_run:
        return 0
    report_path = root / REPORT_FILE_NAME
    moved, skipped = execute_classification_plan(
        plans,
        progress=None if args.quiet else print,
        report_path=report_path,
    )
    print(f"完成：移动 {moved} 个文件，跳过 {skipped} 个文件。")
    print(f"报告：{report_path}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="轻小说分类核心命令行工具")
    parser.add_argument("folder", nargs="?", help="要分类的大文件夹")
    parser.add_argument("--sidecar", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--undo-report", help="按 classification_report.json 撤销一次分类移动")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不移动文件")
    parser.add_argument("--no-network", action="store_true", help="关闭联网识别，只使用本地文件名规则")
    parser.add_argument("--recursive", action="store_true", help="包含子文件夹中的小说文件")
    parser.add_argument("--auto-rename", action="store_true", help="根据电子书内容和在线单卷元数据自动重命名")
    parser.add_argument("--quiet", action="store_true", help="减少命令行输出")
    return parser.parse_args(argv)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.sidecar:
        from .sidecar import SidecarServer

        return SidecarServer().serve_forever()
    if args.undo_report:
        restored, skipped = undo_classification_report(
            Path(args.undo_report),
            progress=None if args.quiet else print,
        )
        print(f"撤销完成：恢复 {restored} 个文件，跳过 {skipped} 个文件。")
        return 0
    if args.folder:
        return run_cli(args)
    print("未提供分类目录。图形界面请运行 run_winui.bat。", file=sys.stderr)
    return 2
