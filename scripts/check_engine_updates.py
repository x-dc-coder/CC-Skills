#!/usr/bin/env python3
"""
check_engine_updates.py — 向后兼容薄壳

原「Paper-reader 引擎更新检查」已泛化为通用工具：
    scripts/skill-update-check.py  （覆盖 npm / pypi / github / self / baseline 五类通道）

本文件保留旧命令名，等价于：
    skill-update-check --focus engines

请优先使用新命令：
    skill-update-check                  # 全量扫描（含 lark-cli / mmdc / keenable 等）
    skill-update-check --focus engines  # 只看 paper-reader 引擎（= 本薄壳行为）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().with_name("skill-update-check.py")


def main() -> int:
    if not TARGET.exists():
        print(f"❌ 未找到主工具: {TARGET}", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, str(TARGET), "--focus", "engines", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
