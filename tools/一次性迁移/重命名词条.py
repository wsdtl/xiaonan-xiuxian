"""把「计量」与「状态」两个词条池改成逐实例唯一、贴合卡片、带修仙味的名字。

## 为什么只改这两类

四类词条里只有这两类是**卡片自己的池子**：

* `计量`（`修改构筑计量.计量`）挂在一名战斗者身上，读写都发生在同一张卡内；
* `状态`（`添加状态.状态.名称`）同理，跨卡只是撞名。

另外两类是**引擎认得的口令**，不能按卡改名：

* `判定`（`修改判定.判定`，取值 `命中/暴击/格挡/控制/连击/反击/任意`）——
  引擎在 `_judgement(context, "连击", ...)` 里按名字取用；
* `规则`（`修改战场规则.名称`）——`方式=移除` 时按名字跨卡匹配同一个规则。

`tools/架构审查/检查词条作用域.py` 负责把这条界限量出来。

## 名字怎么来

`卡名前缀 + 场景词`。场景词按词条种类与卡片方向（功法/真意/器律/战丹…）分别取，
所以四类设计方向不会串味；撞名时先用更长的卡名前缀，再换同义场景词。

读取点的改名只跟着**本实体自己定义**的词条走：引用了别人家的名字说明那张卡
本来就引用了个空池子（`检查词条作用域.py` 会把这些列成「无定义者」或
「被外部读取」），工具不去猜，只报告。

用法::

    python tools/一次性迁移/重命名词条.py
    python tools/一次性迁移/重命名词条.py --apply
"""

import argparse
import collections
import io
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

#: 逐条命名时按这些 glob 找实体；顺序决定报告里的分组顺序。
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "物品/炼器/内容/器律-*.json"),
    ("战丹", "物品/炼丹/内容/丹药/战丹/*.json"),
    ("伤势", "角色/内容/伤势.json"),
)

#: 计量场景词：按「这张卡主要想干什么」分类，每类若干同义词供撞名时升级。
COUNTER_WORDS = {
    "器律": {
        "化盾": ("化盾", "转盾", "承锋"),
        "回复": ("回元", "归元", "返元"),
        "杀伐": ("裂锋", "碎锋", "断锋"),
        "结印": ("凝印", "结印", "聚印"),
        "引诀": ("引诀", "催诀", "唤诀"),
        "蓄势": ("蓄势", "积势", "养势"),
    },
    "功法": {
        "化盾": ("护元", "凝罡", "承锋"),
        "回复": ("归元", "养元", "蓄元"),
        "杀伐": ("裂锋", "破锋", "斩锋"),
        "结印": ("凝印", "结印", "锁印"),
        "引诀": ("引诀", "催诀", "续诀"),
        "蓄势": ("蓄势", "积势", "养势"),
    },
    "真意": {
        "化盾": ("守真", "凝真", "护真"),
        "回复": ("返真", "养真", "归真"),
        "杀伐": ("裂意", "断意", "破意"),
        "结印": ("凝意", "结意", "聚意"),
        "引诀": ("引意", "催意", "续意"),
        "蓄势": ("蓄意", "积意", "养意"),
    },
    "战丹": {
        "化盾": ("护丹", "承丹", "转丹"),
        "回复": ("回丹", "养丹", "归丹"),
        "杀伐": ("裂丹", "破丹", "断丹"),
        "结印": ("凝丹", "结丹", "聚丹"),
        "引诀": ("引丹", "催丹", "续丹"),
        "蓄势": ("蓄丹", "积丹", "养丹"),
    },
}

#: 状态场景词：按卡片方向 + 状态正负取词。
STATUS_WORDS = {
    "器律": {
        "正面": ("器印", "器契", "器兆"),
        "负面": ("器痕", "器隙", "器纹"),
        "中性": ("器标", "器纪", "器数"),
    },
    "功法": {
        "正面": ("灵印", "灵契", "灵兆"),
        "负面": ("气痕", "气隙", "气纹"),
        "中性": ("灵标", "灵纪", "灵数"),
    },
    "真意": {
        "正面": ("真印", "真契", "真兆"),
        "负面": ("意痕", "意隙", "意纹"),
        "中性": ("真标", "真纪", "真数"),
    },
    "战丹": {
        "正面": ("丹印", "丹契", "丹兆"),
        "负面": ("丹痕", "丹隙", "丹纹"),
        "中性": ("丹标", "丹纪", "丹数"),
    },
    "伤势": {
        "正面": ("伤印", "伤契", "伤兆"),
        "负面": ("伤痕", "伤隙", "伤纹"),
        "中性": ("伤标", "伤纪", "伤数"),
    },
}

#: 表里没有的方向用通用词收尾，不静默丢词条。
DEFAULT_COUNTER_WORDS = {
    "化盾": ("化盾", "转盾", "承锋"),
    "回复": ("回元", "归元", "返元"),
    "杀伐": ("裂锋", "破锋", "断锋"),
    "结印": ("凝印", "结印", "聚印"),
    "引诀": ("引诀", "催诀", "唤诀"),
    "蓄势": ("蓄势", "积势", "养势"),
}
DEFAULT_STATUS_WORDS = {
    "正面": ("凝印", "结契", "承兆"),
    "负面": ("裂痕", "暗隙", "残纹"),
    "中性": ("标记", "纪数", "征兆"),
}

#: 意图判定里忽略的中转原子能力：它们只描述结构，不说明这张卡想干什么。
TRANSPARENT = frozenset(
    {"条件执行", "读取数值", "选择目标", "数值条件", "尝试执行", "顺序执行", "重复执行"}
)

#: 一张卡把同一个词同时当计量和状态用时，靠裸名后接的字符判断它指哪一个。
#: 这套字符是从现有 47 张卡的说明里量出来的：`破禁+12`、`破禁清零`、`破禁大于等于6`、
#: `破禁增加2点`、`破禁达到6点`、`破禁30%` 全是计量，引号里的 `“破禁”` 才是状态。
COUNTER_FOLLOW = frozenset("+-×*%0123456789清大达增再小上取等数")


def walk(node):
    """深度优先遍历所有 dict 节点。"""

    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def entity_kind(path: pathlib.Path) -> str:
    relative = path.relative_to(DATA).as_posix()
    for kind, pattern in SURFACES:
        if pathlib.PurePosixPath(relative).match(pattern) or relative == pattern:
            return kind
    return "其他"


def counter_sites(node):
    """产出一个节点里的计量定义与读取。"""

    ability = node.get("能力")
    if ability == "修改构筑计量" and isinstance(node.get("计量"), str):
        yield "定义", node["计量"], node
    elif (
        ability == "读取数值"
        and node.get("来源") == "构筑计量"
        and isinstance(node.get("计量"), str)
    ):
        yield "读取", node["计量"], node


def status_sites(node):
    """产出一个节点里的状态定义与读取。"""

    ability = node.get("能力")
    if ability == "添加状态":
        status = node.get("状态")
        if isinstance(status, dict) and isinstance(status.get("名称"), str):
            yield "定义", status["名称"], status
    elif ability == "选择状态" and isinstance(node.get("名称"), str):
        # 增删改查状态都靠 `选择状态` 指名，所以这里就是状态的全部读取点。
        yield "读取", node["名称"], node
    elif isinstance(node.get("状态"), str) and ability in ("读取数值", "状态条件"):
        yield "读取", node["状态"], node


def intent(ability_node: dict) -> str:
    """看一门技能里出现了哪些原子能力，判断它想要什么。"""

    kinds: set[str] = set()
    shield_only = True
    for node in walk(ability_node):
        ability = node.get("能力")
        if not isinstance(ability, str) or ability in TRANSPARENT:
            continue
        kinds.add(ability)
        if ability == "恢复资源" and node.get("资源") != "护盾":
            shield_only = False
    if "恢复资源" in kinds:
        return "化盾" if shield_only else "回复"
    if "造成伤害" in kinds:
        return "杀伐"
    if "添加状态" in kinds:
        return "结印"
    if "触发技能" in kinds:
        return "引诀"
    return "蓄势"


def scopes(payload: dict):
    """按顶层结构切出「意图作用域」。

    四类卡片把技能摆在 `能力` 里，每个技能各自说明想干什么；战丹与长期伤势没有
    `能力`，监听节点直接挂在 `使用效果` / `战斗状态` 下，整份文档就是一个作用域。
    """

    abilities = payload.get("能力")
    if isinstance(abilities, list) and abilities:
        yield from abilities
    else:
        yield payload


class Entity:
    """一张卡（或一枚战丹、一条长期伤势）以及它自己的词条池。"""

    def __init__(self, kind: str, path: pathlib.Path, index: int, payload: dict):
        self.kind = kind
        self.path = path
        self.index = index
        self.payload = payload
        self.identity = str(payload.get("编号") or payload.get("名称") or path.name)
        self.name = str(payload.get("名称") or path.stem)
        self.counters: dict[str, list[str]] = collections.defaultdict(list)
        self.statuses: dict[str, list[str]] = collections.defaultdict(list)
        self.foreign: dict[str, set[str]] = {"计量": set(), "状态": set()}

        for scope in scopes(payload):
            role = intent(scope)
            for node in walk(scope):
                for mark, name, _holder in counter_sites(node):
                    if mark == "定义":
                        self.counters[name].append(role)
                for mark, name, holder in status_sites(node):
                    if mark == "定义":
                        self.statuses[name].append(str(holder.get("类别") or "正面"))

        defined = {"计量": set(self.counters), "状态": set(self.statuses)}
        for node in walk(payload):
            for kind, sites in (("计量", counter_sites), ("状态", status_sites)):
                for mark, name, _holder in sites(node):
                    if mark == "读取" and name not in defined[kind]:
                        self.foreign[kind].add(name)

    def protected_names(self) -> list[str]:
        """说明里出现但**不是**词条的名字，替换时必须让路。

        除了卡名，还有技能名、战场规则名、构造物名、伤害名……它们都写在 `名称` 字段
        里，和词条共用同一段说明文字。只有 `添加状态` 的 `状态.名称` 与 `选择状态`
        的 `名称` 才是词条本身，其余一律让路，否则会把 `破禁先声` 这类名字切掉一半。

        JSON 里技能名写成 `卡名·短名`，可说明里只写短名（`②[日月无垢]`）。所以每个
        让路名还要按 `·` 拆开逐段登记：卡名 `日月同炉丹经` 的 `无垢` 是状态，而技能
        `日月同炉丹经·日月无垢` 里的 `无垢` 只是名字的一部分，两者不能混。
        """

        names = [self.name]
        for node in walk(self.payload):
            if node.get("能力") in ("添加状态", "选择状态"):
                continue
            value = node.get("名称")
            if not isinstance(value, str) or not value:
                continue
            names.append(value)
            names.extend(part for part in value.split("·") if part)
        return names

    def rename(self, kind: str, old: str, new: str) -> None:
        sites = counter_sites if kind == "计量" else status_sites
        for node in walk(self.payload):
            for _mark, name, holder in sites(node):
                if name == old:
                    if kind == "计量":
                        holder["计量"] = new
                    elif isinstance(holder.get("名称"), str):
                        holder["名称"] = new
                    else:
                        holder["状态"] = new

    def ability_short_names(self) -> set[str]:
        """技能名的短名：JSON 里写 `卡名·短名`，说明里只写短名。"""

        names: set[str] = set()
        for node in walk(self.payload):
            if node.get("能力") not in ("主动技能", "被动技能"):
                continue
            value = node.get("名称")
            if isinstance(value, str) and value:
                names.add(value.rsplit("·", 1)[-1])
        return names

    def normalize_ability_labels(self, tokens: set[str], text: str) -> str:
        """把技能标题里误用的词条长名改回技能自己的短名。

        生成器把技能和它施加的状态取了同一个词（`不灭金身体·法天象地` 施加状态
        `法天象地`），标题就写成了 `②[不灭金身体·状态·法天象地]：耗神18`——技能标题
        挂了状态的长名。这里改成 `②[法天象地]：耗神18`，正文里真正施加状态的地方
        再按词条改名。不改的话，状态一改名，这个技能的标题就从说明里消失了。
        """

        for token in sorted(tokens, key=len, reverse=True):
            for kind in ("计量", "状态"):
                pattern = re.compile(re.escape(f"{self.name}·{kind}·{token}") + r"(?=\]：)")
                text = pattern.sub(lambda _match, value=token: value, text)
        return text

    def rename_text(self, pairs: list[tuple[str, str, str]]) -> list[str]:
        """改写 `说明`：长名与裸名一次过，先让开卡名、技能名、构造物名。

        `说明` 里同一个词条有两种写法——裁定段用 `[卡名·计量·名]`，正文里可能只写
        `名+1`、`自身名大于等于4`、`名清零`。裸名必须一起换，否则玩家看到的规则
        文本会前后不一致。

        一次正则扫完，两条优先级：

        * **让路优先**：状态名里有一批单字（`截`、`拍`、`裂`），常常又是别的名字的
          一部分——`裂` 在 `裂岳锋痕` 里，`拍` 在卡名 `回拍` 里，`破禁` 在构造物
          `破禁先声` 里。让路名排在词条名前面，同一位置让路名先吃掉。
        * **同名兜底**：卡名本身就是一个词条名时（真意 `疗罪` 的状态也叫 `疗罪`），
          只有紧跟在 `·计量·` / `·状态·` 后面的那一次算词条，其余按卡名让路。

        剩下 47 张卡把同一个词同时当计量和状态用（`破禁` 既是计数器又是状态）。这种
        裸名靠后接字符分辨，见 `COUNTER_FOLLOW`；分辨不出来的原样留着，写进报告。
        """

        text = self.payload.get("说明")
        if not isinstance(text, str) or not text:
            return []

        counter_new = {old: new for kind, old, new in pairs if kind == "计量"}
        status_new = {old: new for kind, old, new in pairs if kind == "状态"}
        clash = set(counter_new) & set(status_new)
        mapping = {old: new for _kind, old, new in pairs}

        guard = {name for name in self.protected_names() if name}
        pure_guard = guard - set(mapping)
        overlap = guard & set(mapping)
        alternatives = sorted(pure_guard | set(mapping), key=len, reverse=True)

        text = self.normalize_ability_labels(
            self.ability_short_names() & set(mapping), text
        )

        handled: set[str] = set()
        uncertain: list[str] = []

        def replace(match: re.Match) -> str:
            token = match.group(0)
            if token in pure_guard:
                return token
            start, end = match.span()
            before = text[:start]
            counter_position = before.endswith("·计量·")
            status_position = before.endswith("·状态·")
            if token in overlap and not (counter_position or status_position):
                return token
            handled.add(token)
            if token not in clash:
                return mapping[token]
            if counter_position:
                return counter_new[token]
            if status_position:
                return status_new[token]
            after = text[end] if end < len(text) else ""
            if after and after in COUNTER_FOLLOW:
                return counter_new[token]
            if after == "”" or text[start - 1:start] == "“":
                return status_new[token]
            uncertain.append(token)
            return token

        pattern = re.compile("|".join(re.escape(name) for name in alternatives))
        text = pattern.sub(replace, text)
        self.payload["说明"] = text

        # `X` 还可能留在从它派生出来的新名里（`惑心返` ⊂ `惑心返真`），或者留在让路
        # 名字里（`灵群` ⊂ 构造物名）。把让路名挖掉再找，剩下的才是真残留。
        probe = text
        for name in sorted(guard, key=len, reverse=True):
            probe = probe.replace(name, "")
        leftovers = [
            f"{kind}「{old}」还留在说明里"
            for kind, old, _new in pairs
            if old in probe and old not in handled
        ]
        leftovers.extend(f"跨池同名无法分辨「{old}」" for old in sorted(set(uncertain)))
        return leftovers

    def rename_all(self, pairs: list[tuple[str, str, str]]) -> list[str]:
        """pairs 是 (词条种类, 旧名, 新名)；先改正文，再改说明。"""

        for kind, old, new in pairs:
            self.rename(kind, old, new)
        return self.rename_text(pairs)


def load_entities() -> list[Entity]:
    seen: set[pathlib.Path] = set()
    entities: list[Entity] = []
    for _kind, pattern in SURFACES:
        for path in sorted(DATA.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            kind = entity_kind(path)
            document = json.loads(path.read_text(encoding="utf-8"))
            for index, payload in enumerate(
                document if isinstance(document, list) else [document]
            ):
                if isinstance(payload, dict):
                    entities.append(Entity(kind, path, index, payload))
    return entities


def existing_names(entities: list[Entity]) -> set[str]:
    names: set[str] = set()
    for entity in entities:
        names |= set(entity.counters) | set(entity.statuses)
    return names


def words_for(entity: Entity, kind: str, flavour: str) -> tuple[str, ...]:
    """取该方向的场景词；表里没有的方向退到通用词，最后退到任意一组。"""

    table = COUNTER_WORDS if kind == "计量" else STATUS_WORDS
    default = DEFAULT_COUNTER_WORDS if kind == "计量" else DEFAULT_STATUS_WORDS
    by_kind = table.get(entity.kind) or default
    return (
        by_kind.get(flavour)
        or default.get(flavour)
        or next(iter(by_kind.values()))
        or next(iter(default.values()))
    )


def all_words(entity: Entity, kind: str) -> tuple[str, ...]:
    """该方向能用的全部场景词，用于同方向撞名撞满之后的兜底。"""

    table = COUNTER_WORDS if kind == "计量" else STATUS_WORDS
    default = DEFAULT_COUNTER_WORDS if kind == "计量" else DEFAULT_STATUS_WORDS
    by_kind = table.get(entity.kind) or default
    words: list[str] = []
    for group in list(by_kind.values()) + list(default.values()):
        for word in group:
            if word not in words:
                words.append(word)
    return tuple(words)


def prefixes(entity: Entity) -> tuple[str, ...]:
    """卡名前缀阶梯：先短后长，撞名就往长的方向退。"""

    name = entity.name
    ladder = [name[:2], name[:3], name[:4], name[:5], name]
    ordered: list[str] = []
    for prefix in ladder:
        if prefix and prefix not in ordered:
            ordered.append(prefix)
    return tuple(ordered) or (entity.identity,)


def build_plan(entities: list[Entity]):
    """返回 (改名计划, 撞名兜底记录)。

    候选名只要全局没被占用即可：说明里只替换 `卡名·种类·名` 长名，所以新名
    含有旧名片段不会串改（`rename_text` 里的残留检查负责兜底）。
    """

    taken = existing_names(entities)
    plan: list[tuple[str, str, str, str, str, str]] = []
    fallback: list[str] = []

    for entity in entities:
        for kind, pool in (("计量", entity.counters), ("状态", entity.statuses)):
            for old in sorted(pool):
                flavours = collections.Counter(pool[old])
                flavour = flavours.most_common(1)[0][0]
                words = words_for(entity, kind, flavour)
                new = None
                for word_pool in (words, all_words(entity, kind)):
                    for prefix in prefixes(entity):
                        for word in word_pool:
                            candidate = prefix + word
                            if candidate not in taken:
                                new = candidate
                                break
                        if new:
                            break
                    if new:
                        break
                if new is None:
                    serial = 2
                    while f"{entity.name}{words[0]}{serial}" in taken:
                        serial += 1
                    new = f"{entity.name}{words[0]}{serial}"
                    fallback.append(f"{entity.identity} {kind} 「{old}」-> {new}")
                taken.add(new)
                plan.append((kind, entity.identity, entity.name, entity.kind, old, new))
    return plan, fallback


def write_back(entities: list[Entity]) -> list[str]:
    changed: list[str] = []
    grouped: dict[pathlib.Path, list[Entity]] = collections.defaultdict(list)
    for entity in entities:
        grouped[entity.path].append(entity)
    for path, group in grouped.items():
        document = json.loads(path.read_text(encoding="utf-8"))
        is_list = isinstance(document, list)
        for entity in group:
            if is_list:
                document[entity.index] = entity.payload
            else:
                document = entity.payload
        output = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        if output != path.read_text(encoding="utf-8"):
            path.write_text(output, encoding="utf-8")
            changed.append(path.relative_to(ROOT).as_posix())
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--report", default="_输出/词条改名.txt", help="报告文件")
    args = parser.parse_args()

    entities = load_entities()
    plan, fallback = build_plan(entities)

    leftovers: list[str] = []
    for entity in entities:
        pairs = [
            (kind, old, new)
            for kind, identity, _name, _card_kind, old, new in plan
            if identity == entity.identity
        ]
        if not pairs:
            continue
        for remainder in entity.rename_all(pairs):
            leftovers.append(f"{entity.identity} {entity.name}: {remainder}")

    changed = write_back(entities) if args.apply else []

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    per_kind = collections.Counter(item[0] for item in plan)
    per_card = collections.Counter(item[3] for item in plan)
    out.write(
        f"计划改名 {len(plan)} 处（计量 {per_kind['计量']}，状态 {per_kind['状态']}）；"
        f"唯一名 {len({item[5] for item in plan})}\n"
    )
    for card_kind, count in sorted(per_card.items()):
        out.write(f"  {card_kind}: {count}\n")
    foreign = [
        (entity, kind, sorted(names))
        for entity in entities
        for kind, names in entity.foreign.items()
        if names
    ]
    out.write(f"\n引用了本实体未定义的名字: {len(foreign)} 张\n")
    for entity, kind, names in foreign[:60]:
        out.write(f"  {entity.identity} {entity.name} ({entity.kind}) {kind}: {', '.join(names)}\n")
    out.write(f"\n说明里改不干净的裸名残留: {len(leftovers)}\n")
    for line in leftovers[:60]:
        out.write(f"  {line}\n")
    out.write(f"\n撞名兜底: {len(fallback)}\n")
    for line in fallback[:40]:
        out.write(f"  {line}\n")
    out.write("\n—— 全部改名 ——\n")
    for kind, identity, name, card_kind, old, new in plan:
        out.write(f"{kind}\t{identity}\t{name}\t{card_kind}\t{old}\t{new}\n")
    out.write(f"\n改动文件: {len(changed)}\n")
    for line in changed[:20]:
        out.write(f"  {line}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n")
    out.flush()

    print(f"改名 {len(plan)} 处，唯一名 {len({i[5] for i in plan})}，改动文件 {len(changed)}")
    print(f"详见 {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
