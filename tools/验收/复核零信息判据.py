"""零信息判据的反向复核：把每条修复改回原样，看判据抓不抓得住。

判据好不好，不看它平时报不报，看**它守着的那件事被改回去时它会不会红**。所以这里
把已经修掉的每一处零信息，按当时的旧写法改回文件，跑一遍
tools/架构审查/检查消息零信息.py：

- 判据非零退出 = 抓住（这条修复有判据兜底）；
- 判据零退出 = **漏洞**（这条修复只能靠人守，或者判据该补检查）。

每次改回后无论结果如何都会还原原文件。

    .venv/Scripts/python.exe -X utf8 tools/验收/复核零信息判据.py

它是慢通道（每条要跑一次判据，约 7 秒），不进必过项；新加一条零信息检查时跑它一次，
确认新检查真的在守。**退出码：0 = 全部抓住，1 = 有漏洞。**
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
JUDGE = "tools/架构审查/检查消息零信息.py"
NL = chr(10)

#: 每一项是（说明, 相对路径, 现在的新写法, 当时改回去的旧写法）。
#: 新写法必须逐字出现在文件里，否则这一项算「跳过」——说明代码又变了，要更新这里。
SWAPS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "角色页：等于基准的属性不显示",
        "game/cmd/通用/角色/reply.py",
        ("        and item[1] != baselines.get(item[0], 0)",),
        ("        and item[1] != 0",),
    ),
    (
        "纳戒：空分项不做成可点条目",
        "game/cmd/通用/纳戒/reply.py",
        (
            "        filled = tuple(item for item in category.subcategories if _has_content(item))",
            "        empty += len(category.subcategories) - len(filled)",
            "        if not filled:",
            "            continue",
        ),
        (
            "        filled = tuple(category.subcategories)",
            "        empty += 0",
        ),
    ),
    (
        "炼丹预览：没药引不开栏目",
        "game/cmd/专属/炼丹/reply.py",
        (
            "    if value.beast_material is not None:",
            '        builder.section(text(copy, "预览", "药引"), icon="material")',
            "        _material(builder, 1, value.beast_material)",
        ),
        (
            '    builder.section(text(copy, "预览", "药引"), icon="material")',
            "    if value.beast_material is None:",
            '        builder.line(M.status("无", tone="muted"))',
            "    else:",
            "        _material(builder, 1, value.beast_material)",
        ),
    ),
    (
        "炼器预览：没材料不开栏目",
        "game/cmd/专属/炼器/reply.py",
        (
            "    if value.beast_materials:",
            '        builder.section(text(copy, "预览", "兽引"), icon="material")',
            "        _materials(builder, value.beast_materials, show_relation=False)",
            "    if value.mineral_materials:",
            '        builder.section(text(copy, "预览", "矿材"), icon="item")',
            "        _materials(builder, value.mineral_materials, show_relation=True)",
        ),
        (
            '    builder.section(text(copy, "预览", "兽引"), icon="material")',
            "    _materials(builder, value.beast_materials, show_relation=False)",
            '    builder.section(text(copy, "预览", "矿材"), icon="item")',
            "    _materials(builder, value.mineral_materials, show_relation=True)",
        ),
    ),
    (
        "宗门页：中性倍率不显示",
        "game/cmd/通用/宗门/reply.py",
        (
            "        if value.production_multiplier != 1 or value.facility_cost_multiplier != 1:",
            "            builder.row(",
            "                (",
            '                    _text(copy, "查看", "资源增益"),',
            '                    f"生产/采集 ×{value.production_multiplier:g}",',
            "                ),",
            "                (",
            '                    _text(copy, "查看", "炼制消耗"),',
            '                    f"灵石 ×{value.facility_cost_multiplier:g}",',
            "                ),",
            "            )",
        ),
        (
            "        builder.row(",
            "            (",
            '                _text(copy, "查看", "资源增益"),',
            '                f"生产/采集 ×{value.production_multiplier:g}",',
            "            ),",
            "            (",
            '                _text(copy, "查看", "炼制消耗"),',
            '                f"灵石 ×{value.facility_cost_multiplier:g}",',
            "            ),",
            "        )",
        ),
    ),
    (
        "宗门设施：没材料不开栏目",
        "game/cmd/专属/宗门设施/reply.py",
        (
            "    if materials:",
            '        builder.section("材料", icon="material")',
        ),
        ('    builder.section("材料", icon="material")',),
    ),
    (
        "藏经阁：计数为 0 不单列",
        "game/cmd/专属/藏经阁/reply.py",
        (
            "    if value.total_entries:",
            '        builder.field("功法", M.text(value.total_entries, tone="mystic"))',
        ),
        ('    builder.field("功法", M.text(value.total_entries, tone="mystic"))',),
    ),
    (
        "藏经阁：一页不报页码",
        "game/cmd/专属/藏经阁/reply.py",
        ("    if value.page_count > 1:",),
        ("    if True:",),
    ),
    (
        "阵法列表：一页不报页码",
        "game/cmd/专属/阵法/reply.py",
        (
            "    if value.page_count > 1:",
            "        builder.small(",
            '            text(copy, "列表", "页码", {"当前页": value.page, "总页数": value.page_count})',
            "        )",
        ),
        (
            "    builder.small(",
            '        text(copy, "列表", "页码", {"当前页": value.page, "总页数": value.page_count})',
            "    )",
        ),
    ),
    (
        "宗门战记录：计数为 0 不单列",
        "game/cmd/通用/宗门战/reply.py",
        (
            "    if value.total:",
            '        builder.field(feature.text("查看", "总数"), value.total)',
        ),
        ('    builder.field(feature.text("查看", "总数"), value.total)',),
    ),
    (
        "宗门战记录：一页不报页码",
        "game/cmd/通用/宗门战/reply.py",
        (
            "    if value.page_count > 1:",
            "        builder.small(",
            '            feature.text("格式", "页码", {"当前页": value.page, "总页数": value.page_count})',
            "        )",
            "    return builder.build()",
        ),
        (
            "    return builder.small(",
            '        feature.text("格式", "页码", {"当前页": value.page, "总页数": value.page_count})',
            "    ).build()",
        ),
    ),
    (
        "道侣页：徽章不配复述句（语义重复，判据抓不住）",
        "game/cmd/专属/道侣结交/reply.py",
        (
            "        .line(",
            "            M.status(",
            '                "同行中" if value.is_active else "未同行",',
            '                tone="positive" if value.is_active else "muted",',
            "            )",
            "        )",
        ),
        (
            "        .line(",
            "            M.status(",
            '                "同行中" if value.is_active else "未同行",',
            '                tone="positive" if value.is_active else "muted",',
            "            ),",
            '            " ",',
            '            "正在与你同行" if value.is_active else "如今并未同行",',
            "        )",
        ),
    ),
)


#: 已知抓不住的修复：它们是真修复，但那一类零信息是**语义重复**（同一件事换句话
#: 说），没法安全地泛化成检查——泛化就会误伤「标签: 值」这种正常写法。写在这里是
#: 为了「只对新漏洞报警」：新加一条检查后跑本工具，冒出新漏洞才算问题。
KNOWN_GAPS = frozenset({
    "道侣页：徽章不配复述句（语义重复，判据抓不住）",
})


def _run_judge() -> int:
    done = subprocess.run(
        [str(PYTHON), "-X", "utf8", JUDGE],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    return done.returncode


def main() -> int:
    gaps: list[str] = []
    skipped: list[str] = []
    caught = 0
    for label, relative, now_lines, back_lines in SWAPS:
        target = ROOT / relative
        original = target.read_text(encoding="utf-8").replace(NL.join([chr(13), ""]), NL)
        now = NL.join(now_lines)
        back = NL.join(back_lines)
        if now not in original:
            skipped.append(label)
            print(f"  [跳过] {label}：文件里找不到现在的写法，复核清单要更新")
            continue
        target.write_text(original.replace(now, back, 1), encoding="utf-8")
        try:
            code = _run_judge()
        finally:
            target.write_text(original, encoding="utf-8")
        if code == 1:
            caught += 1
            print(f"  [抓住] {label}")
        else:
            gaps.append(label)
            print(f"  [漏洞] {label}：改回旧写法后判据仍然通过")
    print()
    total = len(SWAPS) - len(skipped)
    fresh = [item for item in gaps if item not in KNOWN_GAPS]
    if fresh:
        print(f"复核总账：{total} 项，抓住 {caught} 项，新漏洞 {len(fresh)} 项 —— {'、'.join(fresh)}")
        return 1
    if gaps:
        print(f"复核总账：{total} 项，抓住 {caught} 项；已知抓不住 {len(gaps)} 项（语义重复，见 KNOWN_GAPS）")
        return 0
    print(f"复核总账：{total} 项全部被判据守住（跳过 {len(skipped)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
