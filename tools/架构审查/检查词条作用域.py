"""词条作用域审查：一个名字到底被谁定义、被谁读取。

改名之前必须知道名字有没有承载**跨卡互动**。如果某张卡读取了一个自己并不
定义的状态名，那这个名字就是两张卡之间的接口——把它改成「全局唯一」等于
把接口剪断。反过来，如果所有读取都落在同一个定义者内部，名字就只是装饰，
可以随便改。

本工具只做一件事：把四类词条（计量/状态/规则/判定）的**定义点**与**读取点**
按所属实体列出来，再判断作用域是「卡内」「共享」还是「无人读」。
"""

import collections
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
PATTERNS = ("**/内容/**/*.json", "**/规则/**/*.json")

#: 词条种类 -> 定义它的原子能力与名字所在的路径。
#:
#: 路径按 `key.subkey` 写：状态的定义体是 `{"名称": ..., "类别": ...}` 整块塞在
#: `状态` 里，规则的名字则是 `修改战场规则` 的兄弟字段 `名称`（`规则` 装的是规则体）。
#: `战前状态` 不是原子能力，而是战丹 `使用效果` 上的整块状态定义，在 `collect()` 里
#: 单独认；它和 `添加状态` 落在同一个状态池里，所以必须一起查重名。
WRITERS = {
    "计量": (("修改构筑计量", "计量"),),
    "状态": (("添加状态", "状态.名称"),),
    "战前状态": (),
    "规则": (("修改战场规则", "名称"),),
    "判定": (("修改判定", "判定"),),
    # 下面四类是**别的命名空间**。不分开就会串台：`险注` 是 `记录战斗事实.名称`
    # 的事实名，被 35 张卡读，混进「状态」桶里会让人以为它是悬空的状态名。
    "事实": (("记录战斗事实", "名称"),),
    "保存结果": (("保存结果", "名称"),),
    "关联": (("修改战斗关联", "名称"),),
    "技能": (("主动技能", "名称"), ("被动技能", "名称")),
}

#: 词条种类 -> 读取它的原子能力与名字所在的路径；第三项是 `来源` 必须等于的值。
#:
#: 增删改查状态都通过 `选择状态` 子节点指名（`状态.名称`），所以 `选择状态` 一条
#: 就覆盖了增加层数/延长/缩短/消耗/复制/转移/移除/支付代价。
READERS = {
    "计量": (("读取数值", "计量", "构筑计量"),),
    "状态": (
        ("读取数值", "状态", None),
        ("状态条件", "状态", None),
        ("选择状态", "名称", None),
    ),
    "战前状态": (),
    "规则": (("读取数值", "规则", None),),
    "判定": (("读取数值", "判定", None),),
    # 事实与保存结果都靠 `读取数值` 的 `来源` 取值分辨。
    "事实": (("读取数值", "名称", "战斗记录"),),
    "保存结果": (("读取数值", "名称", "保存结果"),),
    "关联": (("选择目标", "关联", None),),
    # 技能读取走嵌套的 `选择技能`；这里只登记指名到具体技能的写法。
    "技能": (("选择技能", "名称", None),),
}

#: 数据目录里不是「实体」的路径片段：原子能力定义表里也有同名原子能力。
EXCLUDED = ("/定义/",)

#: 卡片自己的词条池：读写都发生在同一实体内部，名字必须逐实例唯一。
#: `判定` 与 `规则` 不在此列——引擎按名字取用它们，跨实体同名是设计要求。
CARD_LOCAL = ("计量", "状态", "战前状态")


def entities():
    """遍历所有实体文档，产出 (来源标签, 实体编号, 实体)。"""

    for pattern in PATTERNS:
        for path in sorted(DATA.glob(pattern)):
            relative = path.relative_to(ROOT).as_posix()
            if any(part in relative for part in EXCLUDED):
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            entries = document if isinstance(document, list) else [document]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                identity = str(entry.get("编号") or entry.get("名称") or relative)
                yield relative, identity, entry


def collect():
    """返回 词条种类 -> 名字 -> {"定义": [...], "读取": [...]}。"""

    found = {
        kind: collections.defaultdict(lambda: {"定义": [], "读取": []})
        for kind in WRITERS
    }

    def resolve(node, path):
        """按 `key.subkey` 取字符串；取不到或不是字符串时返回 None。"""

        value = node
        for part in path.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value if isinstance(value, str) else None

    def walk(node, kind, entity_id, source):
        if isinstance(node, dict):
            ability = node.get("能力")
            if kind == "战前状态":
                holder = node.get("战前状态")
                if isinstance(holder, dict) and isinstance(holder.get("名称"), str):
                    found[kind][holder["名称"]]["定义"].append((source, entity_id))
            elif isinstance(ability, str):
                for name, path in WRITERS.get(kind, ()):
                    if ability == name and (value := resolve(node, path)):
                        found[kind][value]["定义"].append((source, entity_id))
                for name, path, required in READERS.get(kind, ()):
                    if ability != name:
                        continue
                    if required is not None and node.get("来源") != required:
                        continue
                    if value := resolve(node, path):
                        found[kind][value]["读取"].append((source, entity_id))
            for child in node.values():
                walk(child, kind, entity_id, source)
        elif isinstance(node, list):
            for child in node:
                walk(child, kind, entity_id, source)

    for source, entity_id, entry in entities():
        for kind in WRITERS:
            walk(entry, kind, entity_id, source)

    return found


def _walk_all(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_all(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_all(value)


#: 状态定义体里这些字段有实际作用：少了它们，状态就只是个名字。
STATUS_PAYLOAD = (
    "属性", "标签", "行动限制", "效果免疫", "是否控制", "控制基础命中率",
    "监听", "允许跨构筑", "叠加范围",
)


def inert_report(found) -> str:
    """把「无人读取」拆开：有载荷的、泛选能碰到的、真正的惰性孤岛。

    「没人按名字读」不等于「死」：状态可能带属性加成、可能被 `选择状态` 按分类
    整片扫到、可能被 `支付代价` 当资源花掉。只有**既无载荷、本卡又没有任何泛选
    状态**的，才是纯粹占位。计量则简单些——没人读就是没人读。
    """

    buffer = io.StringIO()
    unread_status = {name for name, record in found["状态"].items() if not record["读取"]}
    unread_counter = {name for name, record in found["计量"].items() if not record["读取"]}
    buckets = collections.Counter()
    islands: list[str] = []
    generic_hits: list[str] = []
    dead_counters: list[str] = []

    for _source, entity_id, entry in entities():
        generic = any(
            node.get("能力") == "选择状态" and not node.get("名称")
            for node in _walk_all(entry)
        )
        for node in _walk_all(entry):
            holder = node.get("状态")
            if node.get("能力") == "添加状态" and isinstance(holder, dict):
                name = holder.get("名称")
                if isinstance(name, str) and name in unread_status:
                    if any(holder.get(key) for key in STATUS_PAYLOAD):
                        buckets["有载荷，是真增益/减益"] += 1
                    elif generic:
                        buckets["无载荷，但本卡有泛选状态会碰到它"] += 1
                        if len(generic_hits) < 20:
                            generic_hits.append(f"{entity_id} {name}")
                    else:
                        buckets["惰性孤岛：无载荷、本卡也没有泛选状态"] += 1
                        if len(islands) < 40:
                            islands.append(f"{entity_id} {name}")
            if node.get("能力") == "修改构筑计量":
                name = node.get("计量")
                if isinstance(name, str) and name in unread_counter:
                    buckets["写了没人读的计量"] += 1
                    if len(dead_counters) < 20:
                        dead_counters.append(f"{entity_id} {name}")

    buffer.write("\n—— 无人读取的定义点怎么分 ——\n")
    for key, count in buckets.most_common():
        buffer.write(f"  {count:>6}  {key}\n")
    buffer.write("\n泛选能碰到的样本:\n")
    for line in generic_hits:
        buffer.write(f"    {line}\n")
    buffer.write("\n惰性孤岛样本（要清就从这里清）:\n")
    for line in islands:
        buffer.write(f"    {line}\n")
    buffer.write("\n写了没人读的计量样本:\n")
    for line in dead_counters:
        buffer.write(f"    {line}\n")
    buffer.write(
        "\n注意：删这些节点会改事件流水——`添加状态前/后` 是有人听的事件，\n"
        "删掉一个惰性状态会顺手删掉它派发的事件。要清就得跑 tools/语料对照.py 对照。\n"
    )
    return buffer.getvalue()


def main() -> int:
    found = collect()
    out = io.TextIOWrapper(open(ROOT / "_词条作用域.txt", "wb"), encoding="utf-8")

    verdicts = collections.Counter()
    failures: list[str] = []
    for kind, names in found.items():
        shared = 0
        internal = 0
        orphan = 0
        cross = 0
        undefended = 0
        for name, record in sorted(names.items()):
            definers = {item for item in record["定义"]}
            readers = {item for item in record["读取"]}
            owners = {entity for _source, entity in definers}
            read_outside = {item for item in readers if item[1] not in owners}
            if not owners:
                undefended += 1
                verdicts[f"{kind}:无定义者"] += 1
                out.write(f"[{kind}] 「{name}」没有定义者，却被 {len(readers)} 处读取\n")
            elif len(owners) > 1:
                shared += 1
                verdicts[f"{kind}:跨实体定义"] += 1
            elif not readers:
                orphan += 1
                verdicts[f"{kind}:无人读取"] += 1
            else:
                internal += 1
                verdicts[f"{kind}:仅内部"] += 1
            if read_outside and owners:
                cross += 1
                out.write(f"[{kind}] 「{name}」被外部读取：\n")
                for source, entity in sorted(read_outside)[:8]:
                    out.write(f"      读 {entity}  ({source})\n")
                for source, entity in sorted(definers)[:8]:
                    out.write(f"      定义 {entity}  ({source})\n")
        out.write(
            f"== {kind}: 名字 {len(names)} 个 | 跨实体定义 {shared} | "
            f"仅内部 {internal} | 无人读取 {orphan} | 无定义者 {undefended} | "
            f"有外部读取 {cross}\n\n"
        )
        if kind in CARD_LOCAL:
            for name, record in sorted(names.items()):
                owners = {entity for _source, entity in record["定义"]}
                if len(owners) > 1:
                    failures.append(f"{kind}「{name}」被多个实体定义：{sorted(owners)}")

    out.write("—— 汇总 ——\n")
    for key in sorted(verdicts):
        out.write(f"{key}: {verdicts[key]}\n")
    out.write(inert_report(found))
    out.write("\n—— 卡片私有池的硬约束 ——\n")
    out.write("计量、状态、战前状态必须逐实例唯一；判定与规则是引擎口令，不在此列。\n")
    if failures:
        out.write(f"不通过：{len(failures)} 项\n")
        for line in failures[:60]:
            out.write(f"  {line}\n")
    else:
        out.write("通过：三类卡片私有池都没有跨实体重名。\n")
    out.flush()

    for kind in sorted(found):
        print(f"{kind}: {len(found[kind])} 个名字")
    if failures:
        print(f"词条作用域审查失败：{len(failures)} 项，详见 _词条作用域.txt")
        return 1
    print("词条作用域审查通过：卡片私有池无跨实体重名")
    return 0


if __name__ == "__main__":
    sys.exit(main())
