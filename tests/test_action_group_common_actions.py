"""宗门同行「共同行动」清单的回归：规则是唯一出处，玩法自报动作要对得上。

口径（负责人拍板 D2）：宗门同行能一起做什么，写成 `data/宗门/规则/宗门.json` 的
`同行.共同行动`（`去`、`探险`、`闭关`、`采药`、`采矿`），**并由代码真读它**——不是
摆一条没人执行的声明。落地方式是：

- 行动组核心初始化时把这份清单读成动作集合（空清单、重复项、非字符串直接拒绝启动）；
- 行路、探险、闭关、采药、采矿五个玩法在各自初始化时**自报动作名**核对，不在清单里
  就拒绝启动。于是「同行能一起做什么」改数据即改行为，玩法层不再各写一份。

这份测试钉住读取面：清单读得进来、`allows` 按清单判、自报面接在五个玩法上、
声明坏掉时启动就报错。
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
from types import SimpleNamespace

import pytest

from game.core.action_group import ActionGroup, ActionGroupService
from game.core.data import JsonDataError, JsonDataService

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
#: 清单里声明的那五个动作（改数据就得改这里，这条正是「规则即事实」）。
声明动作 = ("去", "探险", "闭关", "采药", "采矿")


class _就绪:
    """只为初始化顺序检查提供 `.initialized` 的两个核心替身。"""

    def status(self):
        return SimpleNamespace(initialized=True)



def _写(path: Path, text: str) -> None:
    """原子替换：先写临时文件再 `os.replace`。

    副本是用硬链接建的（快得几乎不花时间），而硬链接上直接 `write_text` 会截断
    同一个 inode、把真实 `data/` 一起写坏；`os.replace` 断开链接、只改副本。
    """

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

_共享数据: JsonDataService | None = None


def _数据() -> JsonDataService:
    """整个模块共用一份只读快照——每例重建一次数据服务是纯浪费。"""

    global _共享数据
    if _共享数据 is None:
        _共享数据 = JsonDataService(DATA)
        _共享数据.initialize()
    return _共享数据


def _服务(tree: pathlib.Path | None = None) -> ActionGroupService:
    data = _数据() if tree is None else JsonDataService(tree)
    if tree is not None:
        data.initialize()
    return ActionGroupService(data, _就绪(), _就绪())


def test_启动期读出共同行动清单() -> None:
    服务 = _服务()
    服务.initialize()
    assert 服务.common_actions() == 声明动作


def test_allows按清单判() -> None:
    服务 = _服务()
    服务.initialize()
    for 动作 in 声明动作:
        assert 服务.allows(动作)
    # 清单外的动作不属于同行共同行动——讨伐、宗门战、切磋都不在里面。
    for 动作 in ("讨伐", "宗门战", "切磋", "交易", ""):
        assert not 服务.allows(动作)


def test_自报清单外的动作拒绝启动() -> None:
    服务 = _服务()
    服务.initialize()
    with pytest.raises(JsonDataError):
        服务.require_common_action("讨伐", "测试玩法")
    # 自报清单内的动作不抛，返回 None。
    assert 服务.require_common_action("探险", "测试玩法") is None


def _改过的数据树(tmp_path: pathlib.Path, 清单: object) -> pathlib.Path:
    tree = pathlib.Path(shutil.copytree(DATA, tmp_path / "data", copy_function=os.link))
    rules = tree / "宗门" / "规则" / "宗门.json"
    raw = json.loads(rules.read_text(encoding="utf-8"))
    raw["同行"]["共同行动"] = 清单
    _写(rules, json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
    return tree


@pytest.mark.parametrize(
    "清单",
    [
        [],
        "去",
        ["去", "去"],
        ["去", ""],
        ["去", 1],
        None,
    ],
)
def test_清单坏掉时拒绝启动(tmp_path, 清单: object) -> None:
    """空清单、字符串、重复项、空项、非字符串、缺项——一律拒绝启动。"""

    服务 = _服务(_改过的数据树(tmp_path, 清单))
    with pytest.raises(JsonDataError):
        服务.initialize()


def test_五个玩法把自报面接在行动组上() -> None:
    """行路／探险／闭关／采药／采矿各自在初始化时报自己的动作名。"""

    import inspect

    from game.features.biguan.service import RetreatFeature
    from game.features.caikuang.service import OreGatheringFeature
    from game.features.caiyao.service import HerbGatheringFeature
    from game.features.tanxian.service import ExplorationFeature
    from game.features.xinglu.service import TravelFeature

    期望 = {
        TravelFeature: '"去"',
        ExplorationFeature: '"探险"',
        RetreatFeature: '"闭关"',
        HerbGatheringFeature: '"采药"',
        OreGatheringFeature: '"采矿"',
    }
    for 类型, 动作 in 期望.items():
        源码 = inspect.getsource(类型.initialize)
        assert f"require_common_action({动作}" in 源码, 类型.__name__


def test_行动组契约没被改动() -> None:
    """顺带钉住这次改动的边界：行动组返回的契约与成员顺序保持原样。"""

    组 = ActionGroup("sect", "领队", ("领队", "跟队"), "宗门-1")
    assert 组.mode == "sect" and 组.group_id == "宗门-1"
    assert 组.participant_user_ids == ("领队", "跟队")
