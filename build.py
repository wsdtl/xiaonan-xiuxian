"""把游戏本体与 data 打进 BUILD/，供「复制进去、替换」的更新方式。

用法（在仓库根）：

    .venv/Scripts/python.exe -X utf8 build.py              # 打包 ＋ 部署自检（默认）
    .venv/Scripts/python.exe -X utf8 build.py --跳过自检    # 只打包
    .venv/Scripts/python.exe -X utf8 build.py --含工具      # 连 tools/ 一起打（维护用）
    .venv/Scripts/python.exe -X utf8 build.py --含测试      # 连 tests/ 一起打
    .venv/Scripts/python.exe -X utf8 build.py --压缩        # 额外产出 BUILD.zip

三条硬规矩：

1. **运行期目录不进包**：`database/`、`.runtime/`、`log/`、`certs/`、`.venv/`、`.env` 一律不拷。
   这些目录（连同它们的旧内容）**替换时原样留在服务器上**，所以更新永远不会碰到存档；
   程序启动时自己判断它们在不在、缺了就建（`database/`、`log/`、`.runtime/` 都已自建）。
2. **只动 BUILD/**：脚本只清空并重建 `BUILD/`，仓库里其它地方一个字节都不碰。
3. **打完自检**：把 BUILD 拷到临时目录、用独立进程按「全新部署」启动一次（不带 database/、log/、.runtime/），
   确认服务能装配起来、这些目录被自动创建——「复制过去能不能跑」由机器来判断，不靠人试。
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
BUILD = ROOT / "BUILD"

#: 游戏本体：入口、启动脚本、依赖、四个运行期包与 data。
本体 = (
    "game", "launch", "message", "static", "data",
    "main.py", "requirements.txt", "start.bat", "start.sh", ".env.example",
)
#: 根目录的说明文档跟着一起走（改数据的人要照着读）。
文档 = (
    "README.md", "系统架构.md", "微服务边界规范.md", "核心设定.md", "说明模版.md",
)
#: 按开关附加。
可选 = {"tools": "含工具", "tests": "含测试"}

#: 永不进包：运行期状态与私密配置。它们的旧内容在替换时原样保留。
不进包 = (
    "BUILD", "database", ".runtime", "log", "certs", ".venv", ".env",
    ".git", ".history", ".pytest_cache", "_输出", "__pycache__",
)


def _copytree(name: str) -> int:
    """拷一个顶层条目，返回文件数；`__pycache__` 与 `.pyc` 不进包。"""

    source = ROOT / name
    target = BUILD / name
    if source.is_dir():
        shutil.copytree(
            source,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        return sum(1 for path in target.rglob("*") if path.is_file())
    shutil.copy2(source, target)
    return 1


def 打包(含工具: bool, 含测试: bool) -> dict:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    文件数 = 0
    缺项: list[str] = []
    for name in 本体:
        if not (ROOT / name).exists():
            缺项.append(name)
            continue
        文件数 += _copytree(name)
    for name in 文档:
        if (ROOT / name).exists():
            文件数 += _copytree(name)
    if 含工具:
        if (ROOT / "tools").exists():
            文件数 += _copytree("tools")
    if 含测试:
        if (ROOT / "tests").exists():
            文件数 += _copytree("tests")
    # 安全断言：运行期目录一个都不许进包。
    泄漏 = [name for name in 不进包 if (BUILD / name).exists()]
    if 泄漏:
        raise SystemExit(f"打包出错：运行期目录进了 BUILD：{泄漏}")
    for name in ("main.py", "game/app.py", "data/说明.md"):
        if not (BUILD / name).exists():
            raise SystemExit(f"打包出错：缺关键文件 {name}")
    大小 = sum(path.stat().st_size for path in BUILD.rglob("*") if path.is_file())
    信息 = {
        "打包时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "来源提交": _提交(),
        "文件数": 文件数,
        "总字节": 大小,
        "含工具": 含工具,
        "含测试": 含测试,
        "运行期目录（不进包，替换时保留）": list(不进包[1:]),
    }
    (BUILD / "部署说明.md").write_text(_部署说明(信息), encoding="utf-8")
    (BUILD / "构建信息.json").write_text(
        json.dumps(信息, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if 缺项:
        raise SystemExit(f"打包出错：仓库里找不到 {缺项}")
    return 信息


def _部署说明(信息: dict) -> str:
    """包里放一份给人看的部署说明：首次装与日常更新的区别，一眼能看懂。"""

    lines = [
        "# 部署说明（由 build.py 生成）",
        "",
        "打包时间：" + str(信息["打包时间"]) + "　来源提交：" + str(信息["来源提交"]),
        "",
        "## 首次部署（只做一次）",
        "",
        "1. 把本目录内容复制到服务器上的安装目录；",
        "2. 把 `.env.example` 复制成 `.env`，按需改端口与密钥——**这一步不能省**，程序会明确报错要求它；",
        "3. 跑 `start.bat`（Windows）或 `start.sh`：它会自建 `.venv`、装依赖再启动。",
        "",
        "`database/`、`log/`、`.runtime/` 这些目录**不用事先建**：程序启动时自己判断、缺了就建。",
        "",
        "## 日常更新（替换）",
        "",
        "1. 把新一份 BUILD 里的内容**复制覆盖**过去；",
        "2. 不要动服务器上的 `.env`（每台机器不同，包里故意不带它）、`database/`（玩家存档）、`log/`、`.runtime/`。",
        "",
        "包里没有这些目录，所以「复制覆盖」不会碰到它们——这正是这套做法的安全点。",
        "",
        "## 包里有什么",
        "",
        "- 游戏本体：`game/`、`launch/`、`message/`、`static/`、`main.py`、启动脚本、依赖清单；",
        "- 全部正式数据：`data/`（规则与内容都在这里，代码只是解释器）；",
        "- 说明文档与 `.env.example` 模板。",
        "",
    ]
    return "\n".join(lines)


def _提交() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10, check=False,
        )
        return result.stdout.strip() or "（未知）"
    except (OSError, subprocess.SubprocessError):
        return "（未知）"


def 压缩() -> pathlib.Path:
    archive = ROOT / "BUILD.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(BUILD.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(BUILD))
    return archive


自检脚本 = """
import pathlib, sys
root = pathlib.Path.cwd()
from main import create_app
create_app()
import game.app as app
print("BASE_DIR =", app.game_config.base_dir if hasattr(app.game_config, "base_dir") else "?")
缺少前 = [name for name in ("database", "log", ".runtime") if not (root / name).exists()]
services = app.build_game_services()
缺少后 = [name for name in ("database", "log", ".runtime") if not (root / name).exists()]
if 缺少后:
    print("自检失败：这些目录没有被自动创建：" + "、".join(缺少后))
    raise SystemExit(1)
print("自检通过：启动前缺 " + ("、".join(缺少前) or "无") + "，启动后运行期目录齐全")
services.core.database.close()
"""


def 自检() -> None:
    """把 BUILD 拷到临时目录，按「全新部署」启动一次。"""

    with tempfile.TemporaryDirectory(prefix="build-自检-") as raw:
        部署 = pathlib.Path(raw) / "install"
        shutil.copytree(BUILD, 部署)
        # 首次部署要人工做的唯一一步：把 `.env.example` 复制成 `.env`（里面是端口与密钥这类
        # 每台机器不同的东西，**故意不进包**——进包就会在替换时覆盖服务器上的真配置）。
        # 自检把这一步替人做掉，才能证明「除此之外，全新目录直接能跑」。
        shutil.copy2(部署 / ".env.example", 部署 / ".env")
        # 全新部署：运行期目录本来就不该在（万一在，先删掉，才能证明「程序会自己建」）。
        for name in ("database", "log", ".runtime"):
            目标 = 部署 / name
            if 目标.exists():
                shutil.rmtree(目标)
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", 自检脚本],
            cwd=部署, capture_output=True, text=True, timeout=300, check=False,
        )
        tail = (result.stdout or "").strip().splitlines()[-2:]
        print("  自检输出：" + " / ".join(tail))
        if result.returncode != 0:
            print((result.stderr or "").strip()[-800:])
            raise SystemExit("自检失败：BUILD 拷到新目录后跑不起来")


def main() -> int:
    parser = argparse.ArgumentParser(description="打包游戏本体与 data 到 BUILD/")
    parser.add_argument("--含工具", action="store_true", help="连 tools/ 一起打包")
    parser.add_argument("--含测试", action="store_true", help="连 tests/ 一起打包")
    parser.add_argument("--压缩", action="store_true", help="额外产出 BUILD.zip")
    parser.add_argument("--跳过自检", action="store_true", help="打完不跑部署自检")
    options = parser.parse_args()

    print("打包到 " + str(BUILD))
    信息 = 打包(options.含工具, options.含测试)
    print("  文件 " + str(信息["文件数"]) + " 个，合计 " + f"{信息['总字节'] / 1048576:.1f} MB" + "，来源提交 " + str(信息["来源提交"]))
    print("  已排除（替换时保留）：" + "、".join(信息["运行期目录（不进包，替换时保留）"]))
    if not options.跳过自检:
        自检()
    if options.压缩:
        print("  压缩包：" + str(压缩()))
    print("完成。把 BUILD 里的内容复制过去替换即可；database/、log/、.runtime/ 会留在原处。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())