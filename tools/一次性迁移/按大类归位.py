"""把 `data/` 的 29 个平铺组件收进七大类：方法、实体与展示各归其位。

## 负责人口径（第 78 轮）

**按大类分文件夹，大类里放细类。** 口径照 `data/说明.md` 那张「主要归属」表：

| 大类 | 组件 |
| --- | --- |
| `基础` | 基础（编号、品级、读取入口） |
| `世界` | 世界、位置、行路 |
| `角色` | 角色 |
| `战斗` | 战斗 |
| `物品` | 基础物品、炼丹、炼器、阵法 |
| `宗门` | 宗门 |
| `玩法` | 交易、先天灵宝、切磋、培养、归元、托管、探险、易形、服丹、补天、讨伐、赠送、道侣、采矿、采药、铜雀台、闭关、队伍 |

**组件名与大类同名时不再多一层**：`基础`、`角色`、`战斗`、`宗门` 四个组件的面就直接放在大类
目录下（`战斗/内容/功法/…`）；其余组件各占一层（`物品/炼丹/内容/丹药/…`、
`世界/位置/规则/附近.json`、`玩法/交易/规则/修行资粮.json`）。于是 `data/世界/内容/…` 与
`data/世界/位置/规则/…` 同住 `世界/`：大类既可以是组件，也可以装组件。

## 读取端要配合的三件事（`game/core/data/files.py`）

1. **扫描目录变成组件相对路径**：`["基础", "世界", "世界/位置", …, "物品/炼丹", …]`。
   校验从「等于所有顶层目录名」放宽成「首段集合等于所有顶层目录名」。
2. **组件清单可以在第二层**：`<组件相对路径>/组件.json`，`组件` 字段等于该路径的最后一段；
   注册的路径必须以该相对路径开头，「组件内语义分类」的判断从 `parts[1]` 顺延到
   `parts[组件路径深度]`。
3. **父目录扫描要让出子组件**：`世界/` 自己是一个组件，`世界/位置/` 又是另一个，`rglob`
   会把子组件的文件捞进父组件的扫描集，判成「没有匹配的读取规则」。`_reserved_segments` 按扫描目录
   算出「哪些首段必须跳过」。

数据集名、实体编号、内容文件名都不变，所以**行为一字不动**：十条通道应当 0 差异。

## 三段

1. **搬目录**：`data/<组件>` 并入 `data/<大类>/<组件>`（合并语义，重跑无效果）。
2. **重写登记**：所有 `组件.json` 的 `读取规则[].路径` 补上大类前缀；`基础/读取规则.json`
   的 `扫描目录` 换成七大类下的组件相对路径。
3. **改写引用**：`game/`、`tools/`、根目录与 `data/` 各说明文档里写死的组件路径
   （`data/炼丹/内容/…`、`炼丹/规则/…`）补上大类前缀。历史记录（`待补内容.md`、
   `一次性迁移/说明.md`）不改——那两处记的是当时的布局。

幂等：三段都以「已经在目标位置 / 已有前缀」为跳过条件。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/按大类归位.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/按大类归位.py --落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

#: 大类 → 组件。「第一个组件与大类同名」是硬要求：它就住在大类目录本身。
大类表: dict[str, tuple[str, ...]] = {
    "基础": ("基础",),
    "世界": ("世界", "位置", "行路"),
    "角色": ("角色",),
    "战斗": ("战斗",),
    "物品": ("基础物品", "炼丹", "炼器", "阵法"),
    "宗门": ("宗门",),
    "玩法": (
        "交易", "先天灵宝", "切磋", "培养", "归元", "托管", "探险", "易形",
        "服丹", "补天", "讨伐", "赠送", "道侣", "采矿", "采药", "铜雀台",
        "闭关", "队伍",
    ),
}

#: 面名 + 组件根文件：路径改写时认这些后继片段。
后继 = r"(?:定义|规则|内容|展示|说明\.md|组件\.json)"
#: 不改写的历史记录：它们记的是当时的布局。
跳过文件 = {
    "data/战斗/内容/待补内容.md",
    "tools/一次性迁移/说明.md",
    "tools/一次性迁移/按大类归位.py",
    # 重建管线要留一份**归位前**的旧路径（`git checkout HEAD --` 只能按提交里的路径取），
    # 所以它由人手工维护，不参与自动改写。
    "tools/一次性迁移/重建数据与库.py",
}
跳过目录 = {".venv", "node_modules", "__pycache__", ".git"}

前缀表: dict[str, str] = {}
for 大类, 组件们 in 大类表.items():
    for 组件 in 组件们:
        前缀表[组件] = 大类 if 组件 == 大类 else f"{大类}/{组件}"
组件归属 = {组件: 大类 for 大类, 组件们 in 大类表.items() for 组件 in 组件们}
改写模式 = {
    组件: re.compile(rf"(?<!{大类}/){组件}(?=/{后继})")
    for 组件, 大类 in 组件归属.items()
    if 前缀表[组件] != 组件
}


def 搬目录(落盘: bool) -> list[str]:
    """把 `data/<组件>` 并入 `data/<大类>/<组件>`。"""

    记录: list[str] = []
    for 大类, 组件们 in 大类表.items():
        for 组件 in 组件们:
            源 = DATA / 组件
            目标 = DATA / 大类 / 组件
            if 前缀表[组件] == 组件:
                continue
            if not 源.is_dir():
                continue
            记录.append(f"{组件} → {大类}/{组件}")
            if not 落盘:
                continue
            目标.mkdir(parents=True, exist_ok=True)
            for 子 in sorted(源.iterdir(), key=lambda p: p.name):
                落点 = 目标 / 子.name
                if 子.is_dir() and 落点.is_dir():
                    _并入目录(子, 落点)
                elif 落点.exists():
                    if 落点.is_dir():
                        shutil.rmtree(落点)
                    else:
                        落点.unlink()
                    shutil.move(str(子), str(落点))
                else:
                    shutil.move(str(子), str(落点))
            if not any(源.iterdir()):
                源.rmdir()
    return 记录


def _并入目录(源: pathlib.Path, 目标: pathlib.Path) -> None:
    """把 `源` 的内容递归并进 `目标`，同名目录继续下探、同名文件以源为准。"""

    目标.mkdir(parents=True, exist_ok=True)
    for 子 in sorted(源.iterdir(), key=lambda p: p.name):
        落点 = 目标 / 子.name
        if 子.is_dir() and 落点.is_dir():
            _并入目录(子, 落点)
            continue
        if 落点.is_dir():
            shutil.rmtree(落点)
        elif 落点.exists():
            落点.unlink()
        shutil.move(str(子), str(落点))
    if not any(源.iterdir()):
        源.rmdir()


def 组件清单们() -> list[pathlib.Path]:
    """`data/` 下每份组件清单，按路径排序。"""

    清单 = [
        path
        for path in sorted(DATA.rglob("组件.json"))
        if not any(段 in 跳过目录 for 段 in path.parts)
    ]
    return 清单


def 规范路径(旧: str, 组件名: str, 前缀: str) -> str:
    """把一条注册路径摆到新布局：组件名那一段换成大类前缀（不是叠加）。"""

    if 前缀 == 组件名:
        return 旧
    # 上一版误写成「前缀 + 原路径」，这里顺手修回来。
    if 旧.startswith(f"{前缀}/{组件名}/"):
        return f"{前缀}/{旧[len(前缀) + 1 + len(组件名) + 1:]}"
    if 旧.startswith(f"{组件名}/"):
        return f"{前缀}/{旧[len(组件名) + 1:]}"
    return 旧


def 重写登记(落盘: bool) -> list[str]:
    """给组件清单的路径补大类前缀，并把读取入口的扫描目录换成新的组件相对路径。"""

    记录: list[str] = []
    for 路径 in 组件清单们():
        相对目录 = 路径.parent.relative_to(DATA).as_posix()
        前缀 = "" if 相对目录 == "." else 相对目录
        数据 = json.loads(路径.read_text(encoding="utf-8"))
        组件名 = str(数据.get("组件") or "")
        期望 = 相对目录.rsplit("/", 1)[-1] if 相对目录 != "." else 组件名
        if 组件名 != 期望:
            记录.append(f"{路径.relative_to(ROOT).as_posix()} 的组件名 {组件名} 与目录 {期望} 不符")
        改动 = False
        for 规则 in 数据.get("读取规则", []):
            旧 = str(规则.get("路径") or "")
            新 = 规范路径(旧, 组件名, 前缀)
            if 新 == 旧:
                continue
            规则["路径"] = 新
            改动 = True
            记录.append(f"{相对目录}/组件.json：{旧} → {新}")
        if 改动 and 落盘:
            写json(路径, 数据)

    入口 = DATA / "基础" / "读取规则.json"
    数据 = json.loads(入口.read_text(encoding="utf-8"))
    新扫描 = [
        前缀表[组件]
        for 大类, 组件们 in 大类表.items()
        for 组件 in 组件们
    ]
    if list(数据.get("扫描目录") or []) != 新扫描:
        记录.append(
            "基础/读取规则.json 扫描目录 → " + "、".join(新扫描)
        )
        if 落盘:
            数据["扫描目录"] = 新扫描
            写json(入口, 数据)
    return 记录


def 写json(路径: pathlib.Path, 数据: object) -> None:
    路径.write_text(
        json.dumps(数据, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def 改写引用(落盘: bool) -> list[str]:
    """把 `game/`、`tools/`、根目录与 `data/` 说明文档里写死的组件路径补上大类前缀。"""

    记录: list[str] = []
    for 路径 in sorted(ROOT.rglob("*")):
        if not 路径.is_file() or 路径.suffix not in {".py", ".md"}:
            continue
        相对 = 路径.relative_to(ROOT).as_posix()
        if any(段 in 跳过目录 for 段 in 路径.parts) or 相对 in 跳过文件:
            continue
        try:
            原文 = 路径.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        新文 = 原文
        for 组件, 前缀 in 前缀表.items():
            if 前缀 == 组件:
                continue
            新文 = 新文.replace(f"data/{组件}/", f"data/{前缀}/")
            # 只换组件名那一段，后面原有的 `/` 留着——`前缀` 里已经含组件名。
            新文 = 改写模式[组件].sub(前缀, 新文)
        # 上一版把组件名换成了「前缀 + /」，会留下 `物品/炼丹//内容` 这种双斜杠，这里修回来。
        for 组件, 前缀 in 前缀表.items():
            if 前缀 != 组件:
                新文 = 新文.replace(f"{前缀}//", f"{前缀}/")
        if 新文 == 原文:
            continue
        记录.append(相对)
        if 落盘:
            路径.write_text(新文, encoding="utf-8")
    return 记录


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--落盘", action="store_true", help="真的搬目录并改写")
    args = parser.parse_args()

    print("== 一、搬目录")
    for 行 in 搬目录(args.落盘):
        print(f"  {行}")
    print("== 二、重写登记")
    for 行 in 重写登记(args.落盘):
        print(f"  {行}")
    print("== 三、改写引用")
    文件们 = 改写引用(args.落盘)
    for 行 in 文件们:
        print(f"  {行}")
    print(f"（{'已落盘' if args.落盘 else '试算'}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
