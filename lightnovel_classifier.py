from __future__ import annotations

# 兼容旧版导入路径；新代码位于 lightnovel_selector 包中。
from lightnovel_selector import *  # noqa: F401,F403
from lightnovel_selector.cli import launch_gui, main, parse_args, print_plan, run_cli  # noqa: F401


if __name__ == "__main__":
    raise SystemExit(main())
