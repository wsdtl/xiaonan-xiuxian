"""验证组件字段契约真的约束数据。

非战斗侧全部实体类别已接入字段契约：境界、伤势、人物状态、阵法、先天灵宝、
道侣、炼器工匠、炼丹师、阵师、丹方。契约由各自核心在启动时通过
`ContractSet.validate` 执行。

本脚本对数据副本做定向破坏，确认契约是**被执行的门禁**而不是装饰性声明，同时
避免启动整条服务依赖链。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/验证组件契约.py
```

退出码 0 表示全部通过（基线通过、各类破坏被拒绝且报错可定位）。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile
from collections.abc import Mapping

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.core.data import ContractSet, JsonDataService  # noqa: E402

#: 类别 -> 契约位置与承载实体。
CASES: dict[str, dict[str, str]] = {
    "境界": {
        "dataset": "角色字段契约",
        "contract_path": "角色/规则/角色字段契约.json",
        "entity_file": "角色/内容/境界.json",
        "remove": "等级下限",
    },
    "伤势": {
        "dataset": "角色字段契约",
        "contract_path": "角色/规则/角色字段契约.json",
        "entity_file": "角色/内容/伤势.json",
        "remove": "治疗",
    },
    "人物状态": {
        "dataset": "角色字段契约",
        "contract_path": "角色/规则/角色字段契约.json",
        "entity_file": "角色/规则/状态/行为状态.json",
        "remove": "可转入",
    },
    "阵法": {
        "dataset": "阵法字段契约",
        "contract_path": "阵法/内容/阵法字段契约.json",
        "entity_file": "阵法/内容/阵法.json",
        "remove": "阵法核心",
    },
    "先天灵宝": {
        "dataset": "先天灵宝字段契约",
        "contract_path": "先天灵宝/内容/先天灵宝字段契约.json",
        "entity_file": "先天灵宝/内容/先天灵宝.json",
        "remove": "权柄",
    },
    "道侣": {
        "dataset": "世界定义",
        "contract_path": "世界/定义/字段契约.json",
        "entity_file": "世界/内容/丹霞州/丹泉苑/丹泉苑道侣.json",
        "remove": "资质范围",
    },
    "炼器工匠": {
        "dataset": "世界定义",
        "contract_path": "世界/定义/字段契约.json",
        "entity_file": "世界/内容/丹霞州/丹霞城/丹霞城炼器工匠.json",
        "remove": "工艺流派",
    },
    "炼丹师": {
        "dataset": "世界定义",
        "contract_path": "世界/定义/字段契约.json",
        "entity_file": "世界/内容/丹霞州/丹泉苑/丹泉苑炼丹师.json",
        "remove": "丹道传承",
    },
    "阵师": {
        "dataset": "世界定义",
        "contract_path": "世界/定义/字段契约.json",
        "entity_file": "世界/内容/丹霞州/丹霞城/丹霞城阵师.json",
        "remove": "阵道传承",
    },
    "丹方": {
        "dataset": "炼丹字段契约",
        "contract_path": "炼丹/规则/炼丹字段契约.json",
        "entity_file": "炼丹/内容/丹方/恢复丹/丹方-恢复精神.json",
        "remove": "炉法",
    },
}


def _load_contract(data_root: pathlib.Path, spec: Mapping[str, str]) -> ContractSet:
    data = JsonDataService(data_root)
    data.initialize()
    return ContractSet.from_dataset(data.dataset(spec["dataset"]), spec["contract_path"])


def main() -> int:
    failures: list[str] = []
    checked = 0
    for category, spec in CASES.items():
        tmp_parent = pathlib.Path(tempfile.mkdtemp())
        root = tmp_parent / "data"
        shutil.copytree(pathlib.Path("data"), root)
        try:
            target = root / spec["entity_file"]
            if not target.is_file():
                failures.append(f"{category}：找不到数据文件 {spec['entity_file']}")
                continue
            original = json.loads(target.read_text(encoding="utf-8"))
            contract = _load_contract(root, spec)

            try:
                contract.validate(original[0], category, f"{category} 基线")
                print(f"[{category}] 基线通过")
                checked += 1
            except Exception as exc:
                failures.append(f"{category}：基线未通过（{exc}）")
                continue

            cases = [
                (
                    f"删除必填字段 {spec['remove']}",
                    lambda rows, key=spec["remove"]: rows[0].pop(key, None),
                    f"{spec['remove']}：缺少字段",
                ),
                (
                    "多写未声明字段",
                    lambda rows: rows[0].__setitem__("契约未声明字段", 1),
                    "规则不认识字段",
                ),
            ]
            for label, mutate, expected in cases:
                broken = json.loads(json.dumps(original, ensure_ascii=False))
                mutate(broken)
                try:
                    contract.validate(broken[0], category, f"{category} 破坏样本")
                except Exception as exc:
                    if expected not in str(exc):
                        failures.append(
                            f"{category} / {label}：报错缺少 {expected!r}，实际 {exc}"
                        )
                else:
                    failures.append(f"{category} / {label}：破坏未被拒绝")
        finally:
            shutil.rmtree(tmp_parent, ignore_errors=True)

    print()
    if failures:
        print(f"组件契约未被正确执行 {len(failures)} 处：")
        for item in failures:
            print(f"  {item}")
        return 1
    print(f"组件契约执行验证通过：{checked} 个类别，每类含基线与两类破坏断言")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
