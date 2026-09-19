"""清掉规则文件里没人读的键与整份没人读的规则文件。

负责人口径（第 83 轮）：**没用的规则删掉**。一条规则只有在**有人读**的时候才算规则；
没人读的键是「声明了却没人执行」的谎，既不约束代码，也看不出代码到底按什么裁定。

判据（保守，宁可漏删不可误删）：

1. 键名是否作为**字符串字面量**出现在 `game/`、`launch/`、`message/` 里——数据键一律中文，
   代码要读它就必须写出这个中文字符串；
2. 排除**能被 f-string 拼出来**的键（`f"{prefix}系数"` 能读 `中段系数`）——把源码里所有含
   占位符的字符串当成模板，键匹配得上就保留；
3. 排除通用键（`说明` / `名称` / `编号` / `条件` …）——读取器与展示层按约定读；
4. **`定义/` 一律不动**（属性表、编号用途是**按表遍历**的词表：`护盾加成` 在 `game/` 里
   0 次字面量，却被 16 个数据文件引用，删了就是删属性）；只有**整份都没人读**的定义文件
   才删（见 `死文件`）。
5. 整份文件都没人读的（`dataset(名字).get(文件主干)` 从不出现）直接删文件。

删完之后空掉的父节点一并摘掉（`藏经阁.生效` 的三个子键全死，`生效` 也就不必留着）。

用法：

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/清死规则.py            # 只报
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/清死规则.py --落盘
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

#: 判据里说的通用键：读取器、展示层与字段契约按约定读，不要求逐处出现字面量。
通用键 = {
    "说明", "名称", "编号", "组件", "读取规则", "路径", "结构", "数据集", "实体类别",
    "编号类别", "池", "字段", "类型", "类别", "必填", "可选", "默认", "选项", "权重",
    "顺序", "排序", "标签", "备注", "资源池字段", "扫描目录", "分组", "标题", "文本",
    "条件", "效果", "范围", "对象", "数值", "描述", "启用", "颜色", "图标", "分页",
    "按钮", "动作", "命令", "参数", "提示", "值", "键", "内容",
}

#: 整份没人读的规则/定义文件。
#:
#: * `世界/位置/规则/同行.json`：`位置规则` 只被读过 `附近`（`location/service.py`），
#:   同行状态机（独行/随队/随宗、排异、锚点）在代码里另有一套，这份是没人执行的声明。
#: * `角色/规则/成长/灵兽修炼.json`：`角色规则` 只取过 人物/道侣/敌方修士/灵兽/修士修炼/
#:   修行所得；灵兽的升级成长走 `灵兽.阶梯[].每级成长`（`enemy/service.py`）。
#: * `角色/规则/突破/境界突破.json`：`角色规则` 从没取过 `境界突破`——突破的裁定
#:   （必成功、永久属性只加不减、每个目标境界一条记录）全在 `character/service.py` 里写死。
#: * `战斗/定义/五行.json`：它是 `战斗/规则/五行.json` 的影子副本，`load_battle_foundation`
#:   先合并 `战斗定义` 再用 `战斗规则.五行` **覆盖**掉同名的 `五行` 键，所以这份从不生效。
#: * `物品/炼丹/规则/战丹.json`：整份只有一条 `强度规则`（强度 ↔ 允许炼制难度）。`炼药规则`
#:   这份数据集只被取过 `丹则` / `炉法` / `难度` / `归脉`（`alchemy/service.py`），
#:   战丹的战前寄存规则读的是 `服丹规则.服丹.战丹`（`medicine/service.py`），是另一份。
死文件 = (
    "世界/位置/规则/同行.json",
    "角色/规则/成长/灵兽修炼.json",
    "角色/规则/突破/境界突破.json",
    "战斗/定义/五行.json",
    "物品/炼丹/规则/战丹.json",
)


#: 运行时报文里出现的键才算「有人读」的**必要条件**，工具与测试里出现的也算消费者——
#: 改数据前先看这几处。
运行期根 = ("game", "launch", "message")
工具根 = ("tools", "tests")


def 源码文本(根s: tuple[str, ...]) -> str:
    片段: list[str] = []
    for 根 in 根s:
        for p in (ROOT / 根).rglob("*.py"):
            if "__pycache__" not in p.parts:
                片段.append(p.read_text(encoding="utf-8"))
    return "\n".join(片段)


def 动态模板() -> list[re.Pattern[str]]:
    """把含占位符的字符串字面量变成正则：键匹配得上就说明它可能是被拼出来的。"""

    模板: list[re.Pattern[str]] = []
    for 根 in 运行期根:
        for p in (ROOT / 根).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.JoinedStr):
                    continue
                文 = ""
                for 段 in node.values:
                    if isinstance(段, ast.Constant) and isinstance(段.value, str):
                        文 += 段.value
                    else:
                        文 += "\x00"
                if "\x00" in 文 and len(文.replace("\x00", "")) >= 1:
                    模板.append(re.compile("^" + re.escape(文).replace("\x00", ".*") + "$"))
    return 模板


#: 清完变成空壳的字典（原本有内容，子键全死）返回它，父层据此把整个节点摘掉。
空壳 = object()


def 清(节点: object, 字面量: set[str], 模板: list[re.Pattern[str]]) -> tuple[object, list[str]]:
    """递归删掉没人读的键；清空的字典整体摘除。返回（新节点, 被删的键路径）。"""

    删除: list[str] = []
    if isinstance(节点, dict):
        结果: dict[str, object] = {}
        for 键, 值 in 节点.items():
            名 = str(键)
            子, 子删 = 清(值, 字面量, 模板)
            删除.extend(f"{名}.{x}" for x in 子删)
            if 子 is 空壳:
                删除.append(名)
                continue
            if 名 in 字面量 or 名 in 通用键 or any(t.match(名) for t in 模板):
                结果[名] = 子
            else:
                删除.append(名)
        if not 结果 and 节点:
            return 空壳, 删除
        return 结果, 删除
    if isinstance(节点, list):
        新列表 = [清(项, 字面量, 模板) for 项 in 节点]
        for _, 子删 in 新列表:
            删除.extend(子删)
        return [x for x, _ in 新列表], 删除
    return 节点, 删除


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--落盘", action="store_true", help="写回 data/（默认只报）")
    args = parser.parse_args()

    文 = 源码文本(运行期根) + "\n" + 源码文本(工具根)
    字面量 = set(re.findall(r'"([^"\n]{1,24})"', 文)) | set(re.findall(r"'([^'\n]{1,24})'", 文))
    模板 = 动态模板()

    行: list[str] = []
    删键总数 = 0
    清空文件: list[str] = []
    for 相对 in 死文件:
        p = DATA / 相对
        if p.is_file():
            行.append(f"删整份文件 {相对}")
            if args.落盘:
                p.unlink()

    面文件 = sorted(p for p in DATA.rglob("*.json") if p.name != "组件.json")
    for p in 面文件:
        段 = p.relative_to(DATA).parts
        # `规则` 面可能在第二层（组件名与大类同名）或第三层（大类/组件/规则）；
        # **`展示/` 底下也有一个叫 `规则` 的子目录**（叙事模板与措辞表），那不是规则面。
        if len(段) < 3 or "规则" not in 段[1:-1] or "展示" in 段[1:-1]:
            continue
        文档 = json.loads(p.read_text(encoding="utf-8"))
        新文档, 删除 = 清(文档, 字面量, 模板)
        if 新文档 is 空壳:
            # 顶层键全死 = 整份文件没人读，交给 死文件 处理（本轮先报出来）。
            清空文件.append(p.relative_to(DATA).as_posix())
            continue
        if not 删除:
            continue
        删键总数 += len(set(删除))
        行.append(f"\n{p.relative_to(DATA).as_posix()}  删 {len(删除)} 个键")
        for x in sorted(set(删除)):
            行.append(f"    - {x}")
        if args.落盘:
            p.write_text(json.dumps(新文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    报告 = pathlib.Path(__file__).resolve().with_name("清死规则清单.txt")
    报告.write_text("\n".join(行) + "\n", encoding="utf-8")
    print(f"删键 {删键总数} 个 · 明细见 {报告.relative_to(ROOT).as_posix()}")
    if 清空文件:
        print("顶层键全死、该整份删掉的文件（加进 死文件 再跑）：")
        for x in 清空文件:
            print("  ", x)
    print(f"（{'已落盘' if args.落盘 else '只报，未写盘'}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
