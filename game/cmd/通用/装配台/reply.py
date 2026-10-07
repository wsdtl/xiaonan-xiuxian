"""装配台消息的纯展示适配。"""
from game.features.zhuangpei import ZhuangpeiResult
from message import Action, DocumentMessage, M


def entry(copy: dict, url: str) -> DocumentMessage:
    return (M.document().header(copy["标题"]).section("公开工具").line(copy["说明"])
            .line(copy["公开说明"]).line(copy["导入说明"])
            .line(M.link(copy["入口"], url))
            .action(Action("assembly.open", copy["入口"], url, behavior="link")).build())


def scheme(title: str, value: ZhuangpeiResult) -> DocumentMessage:
    builder = M.document().header(title).section("整套装配")
    for line in value.lines or ("所有槽位为空",):
        builder.line(line)
    if value.replayed:
        builder.line("这次是重复请求，没有重复消耗库存")
    builder.line("装配码（点一下即可导入，也可以复制）：")
    return builder.line(M.command(value.code, f"导入装配 {value.code}")).build()


def notice(text: str) -> DocumentMessage:
    return M.document().header("装配台").section("清单公开").line(text).build()


def error(text: str, next_step: str = "") -> DocumentMessage:
    builder = M.document().header("装配未生效").section("原因").line(text)
    if next_step:
        builder.line(next_step)
    return builder.build()
