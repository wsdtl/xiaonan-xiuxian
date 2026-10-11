"""注释代码审查：不许把「注释掉的代码」留在源码里。

委托方 2026-10：「我要诗歌一样的代码」——注释掉的代码是最扎眼的一种脏：
它既不执行、又会被后人当参考，读的人分不清那是「暂时的」还是「废的」。

**判法**：一行注释的内容若**能按 Python 解析**（`ast.parse` 成功且有语句）、且含代码特征符
（`=`／`(`／`return`／`import`／`def`／`if`／`for`…），就算注释掉的代码。

**当前全库 0 处真样本、1 处误报**：`game/core/combat/rules.py:19` 的
「一条规则 = 一个拦截点 + 一组条件 + 一个处置」是**散文**，只是恰好长得像赋值语句；
它进白名单（按键字样，不按行号——行号会被上面的改动推走）。
以后**新增**一处注释代码就会红，这就是这条判据要冻住的东西。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查注释代码.py

**退出码：0 = 干净，1 = 有注释掉的代码。**
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_PARTS = {".venv", ".git", "__pycache__", "_输出"}

#: 代码特征符：出现这些才值得试着解析，免得把整篇中文注释都拿去 parse。
CODE_MARKS = (
    "=", "(", "return ", "import ", "def ", "class ",
    "if ", "for ", "while ", "elif ", "else:", "try:", "except", "with ", "raise ", "assert ",
)

#: 已知的「长得像代码、其实是散文」的行；按**字字样**记，不按行号。
KNOWN_PROSE = frozenset({
    "一条规则 = 一个拦截点 + 一组条件 + 一个处置",
})


def main() -> int:
    problems: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").replace("\r", "").split("\n"), 1):
            stripped = line.strip()
            if not stripped.startswith("#") or stripped.startswith("#!"):
                continue
            body = stripped.lstrip("#").strip()
            if not body or body in KNOWN_PROSE:
                continue
            if not any(mark in body for mark in CODE_MARKS):
                continue
            try:
                tree = ast.parse(body)
            except SyntaxError:
                continue
            if not tree.body:
                continue
            problems.append(f"{rel}:{number} 注释掉的代码：{body[:60]}")
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"注释代码审查 {len(problems)} 处")
        return 1
    print("注释代码审查通过：全库没有注释掉的代码")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
