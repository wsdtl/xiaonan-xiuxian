"""先天灵宝激活结果的结算投影。

激活结果由本服务产生，而把它转成结算载荷的动作原先在六个服务里各抄一份
（炼丹、炼器、阵法、采集、闭关、服丹），六份逐字节相同、各自只有一个调用点。
载荷字段由**定义这个类型的包**给出：`InnateTreasureActivation` 的字段一变，
六处不会各自漂移。
"""

from __future__ import annotations

from .contracts import InnateTreasure, InnateTreasureActivation, InnateTreasureEffect


def activation_payload(
    activation: InnateTreasureActivation | None,
) -> dict[str, str] | None:
    """把激活结果转成结算载荷；本回合没有激活时返回 `None`。"""

    if activation is None:
        return None
    return {
        "编号": activation.treasure_id,
        "名称": activation.name,
        "权柄": activation.authority,
        "结果": activation.summary,
    }


def effect_text(effect: InnateTreasureEffect) -> str:
    """能力的可读摘要：「提高通用采集 20%」。

    数值取 `比例`/`数量`/`次数`/`进度` 里**第一个声明过**的字段：比例印成百分数，其余印原值。
    这一段原先在万珍殿页与布阵命令里各写一份（逐字同形），归到定义这个类型的包里。
    """

    for field, suffix in (("比例", "%"), ("数量", ""), ("次数", ""), ("进度", "")):
        if effect.values.get(field) is None:
            continue
        raw = effect.values[field]
        shown = str(int(round(float(raw) * 100))) + suffix if suffix else str(raw)
        return (effect.ability + " " + shown).strip()
    return effect.ability.strip()


def treasure_line(treasure: InnateTreasure) -> str:
    """「灵宝名 · 能力摘要」——页面与回复里描述一件灵宝加成的那一句。"""

    summary = effect_text(treasure.effect)
    return (treasure.name + " · " + summary) if summary else treasure.name


__all__ = ["activation_payload", "effect_text", "treasure_line"]
