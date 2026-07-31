from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .constants import SCAN_MAX_ENTRIES, SCAN_MAX_FILES, SUPPORTED_EXTENSIONS


def validate_classification_root(root: Path) -> Path:
    root = root.expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"大文件夹不存在：{root}")
    if not root.is_dir():
        raise NotADirectoryError(f"不是文件夹：{root}")
    if root.parent == root:
        raise ValueError("为保护系统文件，请选择驱动器或共享根目录下的专用文件夹。")
    return root


def _is_supported_regular_file(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS
    except OSError:
        return False


def find_novel_files(
    root: Path,
    recursive: bool = False,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> list[Path]:
    root = root.expanduser().resolve()
    iterator = root.rglob("*") if recursive else root.iterdir()
    files: list[Path] = []
    for inspected, path in enumerate(iterator, start=1):
        if checkpoint:
            checkpoint()
        if inspected > SCAN_MAX_ENTRIES:
            raise ValueError(f"单次扫描最多检查 {SCAN_MAX_ENTRIES} 个目录项，请缩小目录范围后重试。")
        if not _is_supported_regular_file(path):
            continue
        if recursive:
            try:
                path.resolve().relative_to(root)
            except (OSError, ValueError):
                continue
        files.append(path)
        if len(files) > SCAN_MAX_FILES:
            raise ValueError(f"单次扫描最多支持 {SCAN_MAX_FILES} 个小说文件，请分目录处理。")

    def sort_key(item: Path) -> tuple[str, str, str]:
        relative = item.relative_to(root).as_posix()
        return item.name.casefold(), relative.casefold(), relative

    return sorted(files, key=sort_key)
