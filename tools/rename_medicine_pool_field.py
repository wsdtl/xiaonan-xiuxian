from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in ROOT.joinpath("data").rglob("*.json"):
    text = path.read_text(encoding="utf-8")
    if "额外物品池" in text and path.name != "读取规则.json":
        path.write_text(text.replace("额外物品池", "丹药池"), encoding="utf-8")
service = ROOT / "game/core/enemy/service.py"
text = service.read_text(encoding="utf-8").replace('"额外物品池"', '"丹药池"').replace("额外物品池", "丹药池")
service.write_text(text, encoding="utf-8")
rules = ROOT / "data/基础/读取规则.json"
text = rules.read_text(encoding="utf-8").replace('"额外物品池": "基础物品"', '"丹药池": "基础物品"')
rules.write_text(text, encoding="utf-8")
print("renamed medicine pool field")
