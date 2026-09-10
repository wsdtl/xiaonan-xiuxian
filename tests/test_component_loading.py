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


def test_all_services_and_startup_contracts(tmp_path, monkeypatch):
    from main import create_app
    import game.app as app
    from game.startup import validate_startup_contracts

    create_app()
    isolated = replace(app.game_config.database, path=tmp_path / "game.db")
    monkeypatch.setattr(app, "game_config", replace(app.game_config, database=isolated))
    services = app.build_game_services(data_dir=DATA)
    try:
        validate_startup_contracts(services.core)
        assert services.core.data.status().loaded
    finally:
        services.core.database.close()
