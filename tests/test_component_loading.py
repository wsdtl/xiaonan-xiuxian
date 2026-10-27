"""Component routing failures and real domain initialization."""

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from game.core.data import JsonDataError, JsonDataService
from game.core.combat import expand_build_section

DATA = Path(__file__).resolve().parents[1] / "data"

def _写(path: Path, text: str) -> None:
    """原子替换：先写临时文件再 `os.replace`。

    副本是用硬链接建的（快得几乎不花时间），而硬链接上直接 `write_text` 会截断
    同一个 inode、把真实 `data/` 一起写坏；`os.replace` 断开链接、只改副本。
    """

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@pytest.fixture
def tree(tmp_path):
    """只造加载器需要的最小数据树。

    这些用例验的是「组件清单/路径匹配/游离目录」的失败面，不需要 3131 份正式 JSON；
    复制整棵树会让每个用例花 2 秒建上万个硬链接，把单元测试墙钟锁在 25 秒。
    """

    root = tmp_path / "data"
    (root / "基础" / "定义").mkdir(parents=True)
    (root / "战斗" / "定义").mkdir(parents=True)
    (root / "战斗" / "规则").mkdir(parents=True)
    routing = json.loads((DATA / "基础/读取规则.json").read_text(encoding="utf-8"))
    routing["扫描目录"] = ["基础", "战斗"]
    (root / "基础/读取规则.json").write_text(
        json.dumps(routing, ensure_ascii=False), encoding="utf-8"
    )
    shutil.copy2(DATA / "基础/组件.json", root / "基础/组件.json")
    for name in ("编号.json", "品级.json"):
        shutil.copy2(DATA / "基础/定义" / name, root / "基础/定义" / name)
    (root / "战斗/组件.json").write_text(
        json.dumps(
            {
                "组件": "战斗",
                "读取规则": [
                    {
                        "数据集": "战斗定义",
                        "路径": "战斗/定义/*.json",
                        "结构": "对象",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "战斗/定义/样例.json").write_text("{}", encoding="utf-8")
    return root


@pytest.mark.parametrize("fault", ["missing", "foreign", "unknown", "identity", "unmatched"])
def test_invalid_component_is_rejected(tree, fault):
    manifest = tree / "战斗/组件.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    if fault == "missing":
        manifest.unlink()
    elif fault == "unknown":
        (tree / "未登记").mkdir()
    elif fault == "unmatched":
        (tree / "战斗/规则/未登记.json").write_text("{}", encoding="utf-8")
    else:
        if fault == "identity":
            value["组件"] = "世界"
        else:
            value["读取规则"][0]["路径"] = "世界/内容/地势.json"
        _写(manifest, json.dumps(value, ensure_ascii=False))
    with pytest.raises(JsonDataError):
        JsonDataService(tree).initialize(expand=expand_build_section)


def _搬到第二层(tree, 大类: str, 组件: str) -> None:
    """造一个最小组件，再把它搬进大类目录，并同步清单路径与读取入口。"""

    (tree / 组件).mkdir(exist_ok=True)
    (tree / 组件 / "规则").mkdir(exist_ok=True)
    (tree / 组件 / "规则" / "样例.json").write_text("{}", encoding="utf-8")
    _写(
        tree / 组件 / "组件.json",
        json.dumps(
            {
                "组件": 组件,
                "读取规则": [
                    {"数据集": "样例规则", "路径": f"{组件}/规则/样例.json", "结构": "对象"}
                ],
            },
            ensure_ascii=False,
        ),
    )
    entry = tree / "基础/读取规则.json"
    routing = json.loads(entry.read_text(encoding="utf-8"))
    routing["扫描目录"].append(组件)
    _写(entry, json.dumps(routing, ensure_ascii=False))
    (tree / 大类).mkdir(exist_ok=True)
    shutil.move(str(tree / 组件), str(tree / 大类 / 组件))
    manifest = tree / 大类 / 组件 / "组件.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    for row in value["读取规则"]:
        row["路径"] = f"{大类}/{row['路径']}"
    _写(manifest, json.dumps(value, ensure_ascii=False))
    entry = tree / "基础/读取规则.json"
    routing = json.loads(entry.read_text(encoding="utf-8"))
    routing["扫描目录"] = [
        f"{大类}/{组件}" if x == 组件 else x for x in routing["扫描目录"]
    ]
    _写(entry, json.dumps(routing, ensure_ascii=False))


def test_component_may_sit_in_a_category_directory(tree):
    """大类下放组件：扫描目录写组件相对路径，清单与注册路径都带上大类。"""

    _搬到第二层(tree, "武备", "样例")
    assert JsonDataService(tree).initialize(expand=expand_build_section).loaded


def test_category_directory_without_entry_is_rejected(tree):
    """顶层出现大类，就必须在扫描目录里登记它的子组件。"""

    _搬到第二层(tree, "武备", "样例")
    entry = tree / "基础/读取规则.json"
    routing = json.loads(entry.read_text(encoding="utf-8"))
    routing["扫描目录"] = [x for x in routing["扫描目录"] if x != "武备/样例"]
    _写(entry, json.dumps(routing, ensure_ascii=False))
    with pytest.raises(JsonDataError):
        JsonDataService(tree).initialize(expand=expand_build_section)


def test_nested_component_must_register_under_its_own_prefix(tree):
    """第二层组件的注册路径必须带自己的前缀，不能只写组件名。"""

    _搬到第二层(tree, "武备", "样例")
    manifest = tree / "武备/样例/组件.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["读取规则"][0]["路径"] = value["读取规则"][0]["路径"].removeprefix("武备/")
    _写(manifest, json.dumps(value, ensure_ascii=False))
    with pytest.raises(JsonDataError):
        JsonDataService(tree).initialize(expand=expand_build_section)


def test_all_services_and_startup_contracts(tmp_path, monkeypatch):
    from main import create_app
    import game.app as app
    from game.startup import validate_startup_contracts

    create_app()
    isolated = replace(app.game_config.database, path=tmp_path / "game.db")
    monkeypatch.setattr(app, "game_config", replace(app.game_config, database=isolated))
    services = app.build_game_services(data_dir=DATA)
    try:
        validate_startup_contracts(services.core.player_state)
        assert services.core.data.status().loaded
    finally:
        services.core.database.close()
