"""Component routing failures and real domain initialization."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from game.core.data import JsonDataError, JsonDataService

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def tree(tmp_path):
    return Path(shutil.copytree(DATA, tmp_path / "data"))


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
        manifest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(JsonDataError):
        JsonDataService(tree).initialize()


def _搬到第二层(tree, 大类: str, 组件: str) -> None:
    """把顶层组件搬进一个大类目录，并同步它的清单路径与读取入口。"""

    (tree / 大类).mkdir(exist_ok=True)
    shutil.move(str(tree / 组件), str(tree / 大类 / 组件))
    manifest = tree / 大类 / 组件 / "组件.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    for row in value["读取规则"]:
        row["路径"] = f"{大类}/{row['路径']}"
    manifest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    entry = tree / "基础/读取规则.json"
    routing = json.loads(entry.read_text(encoding="utf-8"))
    routing["扫描目录"] = [
        f"{大类}/{组件}" if x == 组件 else x for x in routing["扫描目录"]
    ]
    entry.write_text(json.dumps(routing, ensure_ascii=False), encoding="utf-8")


def test_component_may_sit_in_a_category_directory(tree):
    """大类下放组件：扫描目录写组件相对路径，清单与注册路径都带上大类。"""

    _搬到第二层(tree, "武备", "战斗")
    assert JsonDataService(tree).initialize().loaded


def test_category_directory_without_entry_is_rejected(tree):
    """顶层出现大类，就必须在扫描目录里登记它的子组件。"""

    _搬到第二层(tree, "武备", "战斗")
    entry = tree / "基础/读取规则.json"
    routing = json.loads(entry.read_text(encoding="utf-8"))
    routing["扫描目录"] = [x for x in routing["扫描目录"] if x != "武备/战斗"]
    entry.write_text(json.dumps(routing, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(JsonDataError):
        JsonDataService(tree).initialize()


def test_nested_component_must_register_under_its_own_prefix(tree):
    """第二层组件的注册路径必须带自己的前缀，不能只写组件名。"""

    _搬到第二层(tree, "武备", "战斗")
    manifest = tree / "武备/战斗/组件.json"
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["读取规则"][0]["路径"] = value["读取规则"][0]["路径"].removeprefix("武备/")
    manifest.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(JsonDataError):
        JsonDataService(tree).initialize()


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
