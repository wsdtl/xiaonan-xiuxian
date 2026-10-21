"""边界规则：命令层不得把「格式」键当正文。

**这条规则的来历**：同一个展示键被当两种角色用——**正文**（命令层把它当异常消息抛出来，本意「你这句哪里不对」）
与**尾注**（渲染层把它补在卡尾，本意「要看写法就发查看帮助」）。两者本来说的不是一回事，共用一个字符串时**改哪边都伤另一边**：
真出过的事就是「撞墙只给尾注、没有原因」那一批（340 次派发扫出 39 处），以及 `山门.json` 那类残留。
委托方定的正解：**拆成两个键**——`错误.格式` 归尾注（统一那句帮助提示）、`错误.写法` 归正文（说清该写什么）。

**本判据管的就是这条边界**：命令层（`game/cmd/**/__init__.py`）把展示键当正文读取时，**键名不得是 `格式`**；
正文一律用含 `写法` 的键。渲染层（`reply.py`）读 `格式` 是合法的——那正是尾注的归处。
运行期那半边由「撞墙要说清为什么」判据把关（它真派发、真看卡上有没有原因）。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查格式键分工.py

**退出码：0 = 干净，1 = 有违规。**
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
CMD = ROOT / "game" / "cmd"

#: 命令层里「两个字符串字面量」的读法，例如 copy("错误", "格式") / text(copy, "错误", "格式")。
#: `page_actions("格式")` 这种**单字面量**是「格式页」的页名，不是键，天然不会命中。
PAIR_WITH_FORMAT = re.compile(r'"([^"]{1,16})"\s*,\s*"格式"')


def main() -> int:
    problems: list[str] = []
    for path in sorted(CMD.rglob("__init__.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.replace(chr(13), "").split(chr(10)), start=1):
            if line.lstrip().startswith("#"):
                continue
            if "page_actions" in line:
                continue
            for match in PAIR_WITH_FORMAT.finditer(line):
                rel = path.relative_to(ROOT).as_posix()
                problems.append(
                    f"{rel}:{number} 命令层把「{match.group(1)}.格式」当正文读；正文该用「写法」键（格式归渲染层当尾注）"
                )
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"格式键分工 {len(problems)} 处有问题")
        return 1
    print("格式键分工 干净")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
