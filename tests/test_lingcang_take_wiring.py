"""宗门灵藏**不可取用**的回归：命令、玩法、核心三层都不得留下取出口。

口径（负责人拍板 D1）：**灵藏只捐入，不取用；成品由万珍殿发放**。灵藏是宗门公共
仓库，没有「取用」属性——玩家能做的只有捐入基础材料与灵石，需要成品走万珍殿的
发放。之前试玩期加过的「取灵藏／取出灵藏」三层接线（命令分支、玩法层方法、核心
层方法）必须连根拔掉，否则它会重新长成一条绕过万珍殿的私取通道。

这份测试因此钉三件事：

- 命令路由表里没有任何「取灵藏／取出灵藏」路由（它当时与 `捐入灵藏` 同组件）；
- 玩法层与核心层都没有 `take_material` / `take_stones`，源码里也不留这两个名字；
- 玩家看得到的说明与展示数据里，不再把「取灵藏」当成一条可用命令来教。

它是**负向**回归：删掉旧接线之后，谁再把它加回来，这里立刻红。
"""

from __future__ import annotations

import inspect
import pathlib
import re

from game.cmd.command import registered_command_routes, registered_commands
from game.core.sect_assets import SectAssetService
from game.features.zongmen_lingcang import LingcangFeature

ROOT = pathlib.Path(__file__).resolve().parents[1]
取用命令 = ("取灵藏", "取出灵藏")
#: 说明里按历史口径点名「已删掉的取灵藏」是允许的（要交代删了什么），但要写成
#: 反引号包住的命令名，且整份说明里不得出现「照抄就能用」的用法行。
历史点名 = re.compile(r"`(取灵藏|取出灵藏)`")


def _命令名() -> list[str]:
    """主命令名（每条注册一项，别名与主名同组件）。"""

    return [str(项[0]) for 项 in registered_commands()]


def _全部路由() -> list[str]:
    """主命令与全部别名——玩家真正能敲进去的字面量。"""

    return [str(项[0]) for 项 in registered_command_routes()]


def test_命令表里没有取灵藏() -> None:
    路由 = _全部路由()
    assert "捐入灵藏" in 路由  # 捐入口子仍在，删的是取用这一半
    assert not [value for value in 路由 if value in 取用命令], 路由


def test_三层都没有取用方法() -> None:
    assert not hasattr(SectAssetService, "take_material")
    assert not hasattr(SectAssetService, "take_stones")
    assert not hasattr(LingcangFeature, "take_material")
    assert not hasattr(LingcangFeature, "take_stones")


def test_取用没在回复层留下痕迹() -> None:
    回复 = inspect.getsource(
        __import__("game.cmd.专属.灵藏.reply", fromlist=["reply"])
    )
    assert "taken_material" not in 回复
    assert "取用灵藏" not in 回复


def test_源码里不留取用名() -> None:
    parts: list[str] = []
    for path in (ROOT / "game").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts.append(path.read_text(encoding="utf-8"))
    source = "\n".join(parts)
    assert "take_material" not in source
    assert "take_stones" not in source
    assert "取出灵藏" not in source


def test_玩家可见说明里不把取灵藏当命令() -> None:
    """说明与展示数据教玩家的必须是现在真有的命令；历史点名只许用反引号标注。"""

    for path in sorted((ROOT / "data").rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".json"}:
            continue
        if path.name == "待补内容.md":
            continue  # 那份是待补清单，按性质会点名历史命令
        文本 = path.read_text(encoding="utf-8")
        去掉历史点名 = 历史点名.sub("", 文本)
        for 名字 in 取用命令:
            assert 名字 not in 去掉历史点名, path.relative_to(ROOT).as_posix()
