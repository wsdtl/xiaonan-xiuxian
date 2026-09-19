"""验证物品契约真的约束数据。

`data/物品/基础物品` 的 `分类.json`、`公共字段.json` 与 `使用效果.json` 声明了丹药
允许的字段集合。这些声明此前没有任何消费者，改动它们不影响游戏；现在丹药核心
在启动时按契约校验。本脚本对副本数据做定向破坏，确认契约是**被执行的门禁**
而不是装饰性声明。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/验证物品契约.py
```

退出码 0 表示全部通过（基线通过、各类破坏被拒绝且报错可定位）。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.core.asset import AssetService  # noqa: E402
from game.core.data import JsonDataService  # noqa: E402
from game.core.database import DatabaseService  # noqa: E402
from game.core.medicine import MedicineService  # noqa: E402

TARGET = "物品/炼丹/内容/丹药/恢复丹/恢复丹-精神.json"


def _initialize_medicine(root: pathlib.Path, database_path: pathlib.Path) -> str:
    """在给定数据副本上初始化丹药核心，返回「通过」或错误摘要。"""

    data = JsonDataService(root)
    data.initialize()
    database = DatabaseService(database_path, busy_timeout_ms=5000)
    database.initialize()
    try:
        asset = AssetService(data, database)
        asset.initialize()
        MedicineService(data, asset).initialize()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    finally:
        database.close()
    return "通过"


def main() -> int:
    tmp_parent = pathlib.Path(tempfile.mkdtemp())
    root = tmp_parent / "data"
    shutil.copytree(pathlib.Path("data"), root)
    database_path = tmp_parent / "probe.db"
    failures: list[str] = []
    try:
        target = root / TARGET
        original = json.loads(target.read_text(encoding="utf-8"))

        # 1. 基线必须通过，否则后续断言没有意义。
        baseline = _initialize_medicine(root, database_path)
        if baseline != "通过":
            failures.append(f"基线数据未通过契约校验：{baseline}")
        print(f"基线：{baseline}")

        # 2. 每类破坏都必须被拒绝，并给出可定位的报错。
        cases: list[tuple[str, object, str]] = [
            ("删除必填的使用效果", lambda e: e.pop("使用效果", None), "使用效果：缺少字段"),
            ("删除公共字段参考价", lambda e: e.pop("参考价", None), "参考价：缺少字段"),
            (
                "效果多写未声明字段",
                lambda e: e.__setitem__(
                    "使用效果", {"类型": "恢复精神", "恢复百分比": 6, "多写字段": 1}
                ),
                "规则不认识字段",
            ),
            (
                "效果类型未声明",
                lambda e: e.__setitem__("使用效果", {"类型": "不存在的类型"}),
                "未在契约中声明",
            ),
            (
                "效果缺必填字段",
                lambda e: e.__setitem__("使用效果", {"类型": "恢复精神"}),
                "恢复百分比：缺少字段",
            ),
        ]
        for label, mutate, expected in cases:
            broken = json.loads(json.dumps(original, ensure_ascii=False))
            mutate(broken[0])
            target.write_text(
                json.dumps(broken, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            outcome = _initialize_medicine(root, database_path)
            if outcome == "通过":
                failures.append(f"{label}：破坏未被拒绝")
            elif expected not in outcome:
                failures.append(f"{label}：报错缺少 {expected!r}，实际 {outcome}")
            print(f"{label}：{outcome}")

        # 3. 使用可选字段必须仍然通过（避免把可选字段误当未知字段）。
        allowed = json.loads(json.dumps(original, ensure_ascii=False))
        allowed[0]["强度"] = 3
        target.write_text(json.dumps(allowed, ensure_ascii=False, indent=1), encoding="utf-8")
        outcome = _initialize_medicine(root, database_path)
        if outcome != "通过":
            failures.append(f"使用可选字段强度被误拒：{outcome}")
        print(f"使用可选字段强度：{outcome}")
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)

    print()
    if failures:
        print(f"物品契约未被正确执行 {len(failures)} 处：")
        for item in failures:
            print(f"  {item}")
        return 1
    print("物品契约执行验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
