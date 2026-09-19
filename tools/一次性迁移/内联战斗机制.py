"""把 `引用战斗机制` 中间层内联成卡片自带的完整战斗文本。

重构后每张卡片（功法 / 真意 / 器律）自己携带完整能力树，不再按六位编号回查
`战斗/内容/战斗机制/`。迁移规则：

1. 引用节点 `{能力: 引用战斗机制, 机制: {编号, 参数}}` 被替换成机制体本身；
2. 机制体按卡片自己的词条表完成槽位绑定（计量上限、状态定义等）后写回；
3. `计量` 直接写成词条自己的短名，不再保留端口名和槽位键；
4. 机制内的嵌套引用用同一份参数继续展开，展开后不再有任何编号引用。

绑定语义写在本文件里，因为引擎侧的绑定模块在重构后已被删除；这里是
「中间层曾经怎么被解释」的唯一留存说明。

用法：
    python tools/一次性迁移/内联战斗机制.py            # 预演，只报告
    python tools/一次性迁移/内联战斗机制.py --apply    # 写回数据
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REF_ABILITIES = ("引用战斗机制", "引用被动机制")
TERM_CATEGORIES = ("计量", "状态", "规则", "判定")
#: 旧数据里写成「承伤增加」的属性：伤害流水线只认 `伤害减免`，正值等于减免负值。
LEGACY_ATTRIBUTE_FIXES = {"承伤增加": "伤害减免"}
#: 中间层删除后统一改掉的术语；出现在能力名与 `读取数值.来源` 取值里。
LEGACY_TERM_RENAMES = (("机制计量", "构筑计量"),)

SOURCES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "物品/炼器/内容/器律-*.json"),
)


class MigrationError(Exception):
    pass


def resolve_term(terms: dict, category: str, slot: str) -> dict:
    table = terms.get(category)
    if not isinstance(table, dict) or not isinstance(table.get(slot), dict):
        raise MigrationError(f"卡片未定义{category}词条：{slot}")
    return table[slot]


def bind_mechanism_parameters(terms: dict, parameters: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for port, slot in parameters.items():
        category = str(port).split(":", 1)[0]
        if category not in TERM_CATEGORIES:
            raise MigrationError(f"未知机制参数端口：{port}")
        table = terms.get(category)
        if not isinstance(table, dict) or slot not in table:
            raise MigrationError(f"机制参数未绑定到{category}词条：{slot}")
        result[str(port)] = str(slot)
    return result


def bind_term_slots(terms: dict, parameters: dict, node: object) -> object:
    """把卡片词条展开进机制副本；没有端口时只做一次深拷贝。"""

    copied = copy.deepcopy(node)
    if not parameters:
        return copied
    return _resolve(copied, terms, bind_mechanism_parameters(terms, parameters))


def _resolve(value: object, terms: dict, parameters: dict[str, str]) -> object:
    if isinstance(value, list):
        return [_resolve(item, terms, parameters) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _resolve(child, terms, parameters) for key, child in value.items()}
    for port, slot in parameters.items():
        category, _, short = port.partition(":")
        known = {port, short, slot, slot.rsplit("_", 1)[-1]}
        known.discard("")
        if category == "计量":
            current = result.get("计量")
            if isinstance(current, str) and current.strip() in known:
                term = resolve_term(terms, "计量", slot)
                result["计量"] = short
                if "上限" in term:
                    result["最高值"] = term["上限"]
        elif category == "状态":
            current = result.get("状态")
            if isinstance(current, str):
                # 字符串 `状态` 是状态身份；机制体里的短名就是定义实际使用的
                # 名字，替换成词条对象会让 `状态条件` / `状态层数` 永远匹配不上。
                pass
            elif isinstance(current, dict):
                term = resolve_term(terms, "状态", slot)
                if "能力" in current:
                    # `选择状态` 是选择器而不是状态定义：只借状态身份和标签。
                    for key in ("名称", "标签"):
                        if key in term and key not in current:
                            current[key] = copy.deepcopy(term[key])
                else:
                    result["状态"] = {**term, **current}
        elif category == "规则" and "规则" in result:
            term = resolve_term(terms, "规则", slot)
            result["名称"] = term.get("显示名", term.get("名称", short))
            for key in ("规则", "重复处理", "来源退场时移除"):
                if key in term:
                    result[key] = copy.deepcopy(term[key])
        elif category == "判定" and "判定" in result:
            term = resolve_term(terms, "判定", slot)
            result["判定"] = term.get("判定", short)
            result["方式"] = term.get("方式", "必定成功")
            if "次数" in term:
                result["次数"] = term["次数"]
    return result


def load_mechanisms() -> dict[str, dict]:
    """读取待内联的机制库；中间层删除后返回空库，工具退化为残留检查。"""

    library: dict[str, dict] = {}
    directory = DATA / "战斗/内容/战斗机制"
    if not directory.exists():
        return library
    for path in sorted(directory.glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            library[str(entry["编号"])] = entry["节点"]
    return library


def parse_reference(raw: object, inherited: dict[str, str]) -> tuple[str, dict[str, str]]:
    if isinstance(raw, dict):
        mechanism_id = str(raw.get("编号") or "").strip()
        parameters = raw.get("参数")
        if isinstance(parameters, dict) and parameters:
            return mechanism_id, {str(k): str(v) for k, v in parameters.items()}
        return mechanism_id, dict(inherited)
    return str(raw or "").strip(), dict(inherited)


class Inliner:
    def __init__(self, library: dict[str, dict]) -> None:
        self.library = library
        self.stats = Counter()

    # -- 词条短名 ---------------------------------------------------------
    @staticmethod
    def _check_port_names(parameters: dict[str, str]) -> None:
        """计量端口后缀必须与词条自己声明的短名一致，否则改名会丢语义。"""

        for port, slot in parameters.items():
            category, separator, suffix = port.partition(":")
            if not separator or category not in ("计量", "状态"):
                continue
            declared = slot.rsplit("_", 1)[-1]
            if suffix != declared:
                raise MigrationError(f"端口名与词条短名不一致：{port} -> {slot}")

    # -- 绑定 -------------------------------------------------------------
    def _bind(self, body: dict, terms: dict, parameters: dict[str, str]) -> dict:
        return bind_term_slots(terms, dict(parameters), body)

    def expand(self, raw: object, terms: dict, inherited: dict[str, str]) -> dict:
        mechanism_id, parameters = parse_reference(raw, inherited)
        body = self.library.get(mechanism_id)
        if body is None:
            raise MigrationError(f"引用不存在的战斗机制：{mechanism_id or '<空>'}")
        self._check_port_names(parameters)
        self.stats["引用"] += 1
        self.stats[f"引用_{'参数化' if parameters else '裸引用'}"] += 1
        bound = self._bind(body, terms, parameters)
        return self._resolve_nested(bound, terms, parameters)

    def _resolve_nested(
        self,
        node: object,
        terms: dict,
        parameters: dict[str, str],
    ) -> object:
        if isinstance(node, dict):
            if node.get("能力") in REF_ABILITIES:
                return self.expand(node.get("机制"), terms, parameters)
            return {
                key: self._resolve_nested(value, terms, parameters)
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [self._resolve_nested(item, terms, parameters) for item in node]
        return node

    # -- 卡片 -------------------------------------------------------------
    def card(self, entity: dict) -> dict:
        terms = entity.get("词条")
        terms = terms if isinstance(terms, dict) else {}
        migrated = {key: copy.deepcopy(value) for key, value in entity.items() if key != "词条"}
        before = _count_refs(entity)
        migrated["能力"] = self._resolve_nested(
            copy.deepcopy(entity.get("能力")), terms, {}
        )
        after = _count_refs(migrated)
        if after:
            raise MigrationError(f"{entity.get('编号')} 内联后仍残留 {after} 个机制引用")
        if before == 0:
            self.stats["无引用卡片"] += 1
        return migrated


def _count_refs(node: object) -> int:
    total = 0
    if isinstance(node, dict):
        if node.get("能力") in REF_ABILITIES:
            total += 1
        for value in node.values():
            total += _count_refs(value)
    elif isinstance(node, list):
        for value in node:
            total += _count_refs(value)
    return total


def fix_legacy_attributes(node: object) -> int:
    """把 `属性` 表里流水线不认识的旧名改写成真正的属性；返回改写数量。"""

    fixed = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "属性" and isinstance(value, dict):
                for old, new in LEGACY_ATTRIBUTE_FIXES.items():
                    if old in value:
                        value[new] = -value.pop(old)
                        fixed += 1
            fixed += fix_legacy_attributes(value)
    elif isinstance(node, list):
        for value in node:
            fixed += fix_legacy_attributes(value)
    return fixed


def rename_legacy_terms(node: object) -> int:
    """把中间层时代的术语改写成现在的名字；返回改写数量。

    只处理取值，不动键名：`机制计量` 只作为 `能力` / `来源` 的值出现。
    """

    renamed = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                for old, new in LEGACY_TERM_RENAMES:
                    if old in value:
                        node[key] = value.replace(old, new)
                        renamed += 1
                        break
            else:
                renamed += rename_legacy_terms(value)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, str):
                for old, new in LEGACY_TERM_RENAMES:
                    if old in value:
                        node[index] = value.replace(old, new)
                        renamed += 1
                        break
            else:
                renamed += rename_legacy_terms(value)
    return renamed


#: 卡片 `说明` 里生成器留下的「（机制：600xxx）」括号引用；中间层删除后不再成立。
MECHANISM_MENTION = re.compile(r"（机制：[^）]*）")


def strip_mechanism_mentions(entity: dict) -> int:
    """去掉 `说明` 里指向已删除编号的括号引用；返回改写数量。"""

    text = entity.get("说明")
    if not isinstance(text, str) or "（机制：" not in text:
        return 0
    rewritten, count = MECHANISM_MENTION.subn("", text)
    entity["说明"] = rewritten
    return count


#: 状态承载载体：战丹的使用效果和长期伤势的战斗状态都直接寄存监听节点。
STATUS_SOURCES = (
    (
        "战丹",
        "物品/炼丹/内容/丹药/战丹/*.json",
        ("使用效果", "战斗机制"),
        ("使用效果", "监听"),
    ),
    (
        "长期伤势",
        "角色/内容/伤势.json",
        ("战斗状态", "机制"),
        ("战斗状态", "监听"),
    ),
)


def migrate_status_sources(library: dict[str, dict], apply: bool) -> list[str]:
    report: list[str] = []
    for label, pattern, (holder, field), (out_holder, out_field) in STATUS_SOURCES:
        total = 0
        rewritten = 0
        for path in sorted(DATA.glob(pattern)):
            raw_text = path.read_text(encoding="utf-8")
            document = json.loads(raw_text)
            is_list = isinstance(document, list)
            entries = document if is_list else [document]
            for entry in entries:
                holder_value = entry.get(holder)
                if not isinstance(holder_value, dict) or field not in holder_value:
                    continue
                bodies = []
                for mechanism_id in holder_value.pop(field) or ():
                    body = library.get(str(mechanism_id))
                    if body is None:
                        raise MigrationError(
                            f"{path.name} 引用不存在的战斗机制：{mechanism_id}"
                        )
                    if body.get("能力") != "监听事件":
                        raise MigrationError(
                            f"{path.name} 的机制 {mechanism_id} 不是监听节点，"
                            "状态只能寄存监听"
                        )
                    bodies.append(copy.deepcopy(body))
                    total += 1
                if bodies:
                    holder_value[out_field] = bodies
                rewritten += 1
            output = json.dumps(
                entries if is_list else entries[0], ensure_ascii=False, indent=2
            ) + "\n"
            if output != raw_text:
                if apply:
                    path.write_text(output, encoding="utf-8")
        report.append(f"{label}: {rewritten} 个实体, 内联 {total} 个监听节点")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    args = parser.parse_args()

    library = load_mechanisms()
    inliner = Inliner(library)
    report: list[str] = []
    changed_files = 0
    sizes = {"before": 0, "after": 0}

    for label, pattern in SOURCES:
        cards = 0
        for path in sorted(DATA.glob(pattern)):
            raw_text = path.read_text(encoding="utf-8")
            document = json.loads(raw_text)
            is_list = isinstance(document, list)
            entries = document if is_list else [document]
            migrated = []
            for entry in entries:
                try:
                    migrated.append(inliner.card(entry))
                except RecursionError as exc:
                    raise MigrationError(
                        f"{path.name} 实体 {entry.get('编号')} 迁移失败："
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                except MigrationError as exc:
                    raise MigrationError(
                        f"{path.name} 实体 {entry.get('编号')} 迁移失败：{exc}"
                    ) from exc
            output = json.dumps(
                migrated if is_list else migrated[0],
                ensure_ascii=False,
                indent=2,
            ) + "\n"
            cards += len(migrated)
            sizes["before"] += len(raw_text)
            sizes["after"] += len(output)
            if output != raw_text:
                changed_files += 1
                if args.apply:
                    path.write_text(output, encoding="utf-8")
        report.append(f"{label}: {cards} 张卡片")

    report.extend(migrate_status_sources(library, args.apply))

    legacy = 0
    for label, pattern in SOURCES:
        for path in sorted(DATA.glob(pattern)):
            raw_text = path.read_text(encoding="utf-8")
            document = json.loads(raw_text)
            is_list = isinstance(document, list)
            entries = document if is_list else [document]
            count = sum(fix_legacy_attributes(entry) for entry in entries)
            count += sum(strip_mechanism_mentions(entry) for entry in entries)
            count += sum(rename_legacy_terms(entry) for entry in entries)
            if not count:
                continue
            legacy += count
            output = json.dumps(
                entries if is_list else entries[0], ensure_ascii=False, indent=2
            ) + "\n"
            if args.apply:
                path.write_text(output, encoding="utf-8")
    report.append(f"旧属性名/术语改写与说明清理: {legacy} 处")

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / "_输出" / "migrate.txt", "wb"), encoding="utf-8")
    out.write("\n".join(report) + "\n")
    out.write(f"机制库: {len(library)} 条\n")
    for key, value in sorted(inliner.stats.items()):
        out.write(f"  {key}: {value}\n")
    out.write(
        f"改动文件: {changed_files}  体积 {sizes['before']:,} -> {sizes['after']:,} 字符 "
        f"(净增 {sizes['after'] - sizes['before']:+,})\n"
    )
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n")
    out.flush()
    print(f"改动文件: {changed_files}；详见 _输出/migrate.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
