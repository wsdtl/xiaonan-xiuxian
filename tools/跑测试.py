"""跑 `tests/`：单进程 pytest，临时目录由全量核对统一指向 `_输出/临时`。

    .venv/Scripts/python.exe -X utf8 tools/跑测试.py

**退出码：0 = 全部通过，1 = 有失败。**
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    scratch = ROOT / "_输出" / "临时"
    scratch.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(scratch), "TMP": str(scratch)}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "tests"],
        cwd=ROOT,
        env=env,
    )
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
