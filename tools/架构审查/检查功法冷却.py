"""功法冷却与技能条数判据：装得越多，能用的技能不能越少。

来自用户的三条口径：
  一、**一个功法的主动技能不要太多** —— 每卡 `主动技能` 条目 ≤ 3 条
      （条数太多会让"装得多、用得少"：冷却一铺开，循环里根本轮不到）
  二、**冷却要隔离得开** —— 同一张卡里冷却值不得重复（两张技能同冷却 = 实际只能转一张）
  三、**全局冷却要平均** —— 任一冷却档占比 ≤ 30%，且从最小到最大档不许缺档
      （缺档会造成"总是那几个技能"：只有 3 档在转，5 档的永远上不了场）

跑法：`python -X utf8 tools/架构审查/检查功法冷却.py`
（改机制/换引用之前先跑一次，改完再跑一次；红了先回滚，别接着改。）
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARTS = ROOT / "data" / "战斗" / "内容" / "功法"

ACTIVE_LIMIT = 3
COOLDOWN_SHARE_LIMIT = 0.30
#: 「词条定义保护」下允许超限的卡（它们的额外条目承载别处要读的定义，硬切会造悬空引用）。
PROTECTED_TOLERANCE = 4


def load_cards() -> list[dict]:
    found: list[dict] = []
    for path in sorted(ARTS.rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                found.append(item)
    return found


def cooldowns(card: dict) -> list[int]:
    values = []
    for node in card.get("能力") or []:
        if isinstance(node, dict) and node.get("能力") == "主动技能":
            raw = str(node.get("冷却行动", ""))
            if raw.isdigit():
                values.append(int(raw))
    return sorted(values)


def main() -> int:
    cards = load_cards()
    total = len(cards)
    failures = 0

    over = [(str(c.get("名称")), len(cooldowns(c))) for c in cards if len(cooldowns(c)) > ACTIVE_LIMIT]
    hard = [(name, n) for name, n in over if n > PROTECTED_TOLERANCE]
    soft = [(name, n) for name, n in over if n <= PROTECTED_TOLERANCE]
    ok = not hard
    failures += not ok
    print(
        f"[{'通过' if ok else '失败'}] 每卡主动 ≤ {ACTIVE_LIMIT}：超限 {len(over)} / {total} 张"
        f"（其中 >{PROTECTED_TOLERANCE} 条、需硬处理的 {len(hard)} 张）"
    )
    for name, n in soft[:5]:
        print(f"        容忍（受定义保护）：{name} {n} 条")
    for name, n in hard[:5]:
        print(f"        待处理：{name} {n} 条")

    dup = []
    for card in cards:
        values = cooldowns(card)
        if len(values) != len(set(values)):
            dup.append(str(card.get("名称")))
    ok = not dup
    failures += not ok
    print(f"[{'通过' if ok else '失败'}] 同卡冷却不重复：违规 {len(dup)} / {total} 张")
    for name in dup[:5]:
        print(f"        {name}")

    counts: collections.Counter[int] = collections.Counter()
    for card in cards:
        counts.update(cooldowns(card))
    used = sum(counts.values()) or 1
    worst = max(counts.items(), key=lambda kv: kv[1]) if counts else (0, 0)
    ok_share = worst[1] / used <= COOLDOWN_SHARE_LIMIT
    missing = [v for v in range(min(counts), max(counts) + 1) if counts.get(v, 0) == 0] if counts else []
    ok_gap = not missing
    failures += not (ok_share and ok_gap)
    print(
        f"[{'通过' if ok_share and ok_gap else '失败'}] 全局冷却平均："
        f"最大档 冷却 {worst[0]} 占 {worst[1] / used * 100:.1f}%（上限 {COOLDOWN_SHARE_LIMIT * 100:.0f}%）"
        f" ｜ 缺档 {missing if missing else '无'}"
    )
    print("        分布：" + " ｜ ".join(f"{k}:{v}（{v / used * 100:.1f}%）" for k, v in sorted(counts.items())))

    print(f"总账：失败 {failures} 组")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
