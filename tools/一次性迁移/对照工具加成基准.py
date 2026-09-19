"""一次性：把各对照工具的陪练属性里的加成基准从 0 改成 100。

加成口径的基准补到 100 之后，`"伤害加成": 0` 不再是「不增不减」，而是「伤害 ×0」——
十个对照工具各抄了一份同样的陪练属性，全都会因此把每场战斗都改掉（实测语料 1967/1967 差异）。
这里把它们统一改成 100，并在每份属性表上面留一行说明，免得下次又被当成笔误改回去。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/对照工具加成基准.py
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
工具 = ROOT / "tools"
标记 = "#: 加成口径的基准是 100（不增不减）；这里写 0 等于把伤害乘成 0。"
旧 = '"伤害加成": 0'
新 = '"伤害加成": 100'

改动: list[str] = []
for path in sorted(工具.glob("*.py")):
    text = path.read_text(encoding="utf-8")
    if 旧 not in text:
        continue
    行 = text.splitlines(keepends=True)
    出: list[str] = []
    for index, line in enumerate(行):
        if 旧 in line and 标记 not in "".join(出[-2:]):
            缩进 = line[: len(line) - len(line.lstrip())]
            出.append(f"{缩进}{标记}\n")
        出.append(line.replace(旧, 新))
    path.write_text("".join(出), encoding="utf-8")
    改动.append(f"{path.relative_to(ROOT).as_posix()}（{text.count(旧)} 处）")

print(f"改了 {len(改动)} 个文件：" if 改动 else "没有需要改的文件（重跑无效果）")
for item in 改动:
    print("  " + item)
