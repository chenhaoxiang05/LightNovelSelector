from __future__ import annotations

# 保留历史 Python API 导入路径；图形界面统一由 WinUI 3 提供。
from lightnovel_selector import *  # noqa: F401,F403
from lightnovel_selector.cli import main, parse_args, print_plan, run_cli  # noqa: F401


if __name__ == "__main__":
    raise SystemExit(main())
