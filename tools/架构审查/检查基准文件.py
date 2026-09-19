"""基准文件命名审查：`tools/基准` 下不许出现「野文件」。

第 26 轮踩过一次：`语料对照.py` 的摘要一律写成 `<输出>.sem`，而我传的 `<输出>` 是
`tools/基准/语料摘要.json`，于是产出 `语料摘要.json.sem` 并入库——**真正的基准没被刷新**，
下一批的差异核对混进了上一批的旧差异。当时是靠「越界差异的编号全是上一批的」才反推出来。

这条检查把这类错变成一次显式的失败：**基准目录**里凡是名字里带两个后缀的（`*.json.sem`
这类拼接产物）一律报错。只查 `tools/基准`——`_输出/` 下的 `语料.sem` 是跑语料用的临时摘要，
本就不入库，不在管辖范围（否则每跑一次语料就红一片，检查会被人无视）。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查基准文件.py

**退出码：0 = 干净，1 = 有野文件。**
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINE_DIR = ROOT / "tools" / "基准"

#: 摘要文件名形如 `<基准名>.sem`：再往前还挂着一个已知数据后缀的就是拼接产物。
KNOWN_STEMS = (".json", ".txt", ".md", ".csv")


def strays(folder: pathlib.Path) -> list[pathlib.Path]:
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix != ".sem":
            continue
        if path.stem.endswith(KNOWN_STEMS):
            found.append(path)
    return found


def main() -> int:
    problems = strays(BASELINE_DIR)
    if not problems:
        print(f"基准文件命名审查通过：{BASELINE_DIR.relative_to(ROOT)} 下无拼接产物")
        return 0
    for path in problems:
        print(f"  野文件 {path.relative_to(ROOT)}")
    print("这些是「传错输出名」留下的拼接产物：真基准没被刷新。删掉并按基准名重刷。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
