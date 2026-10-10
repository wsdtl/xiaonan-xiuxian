from game.features.butian import ButianFeature, ButianResult
from message import DocumentMessage, M
from ...presentation import format_lines


def result(feature: ButianFeature, value: ButianResult) -> DocumentMessage:
    return (
        M.document()
        .header(feature.copy("结算", "标题"))
        .section(value.target_name, icon="cultivation")
        .line(M.status("补天完成", tone="positive"))
        .field("补正境界", value.realm_name)
        .field(value.attribute, M.text(value.value, tone="cultivation"))
        .small(feature.copy("结算", "完成"))
        .build()
    )


def error(feature: ButianFeature, message: str) -> DocumentMessage:
    builder = M.document().section(feature.copy("错误", "标题"), icon="notice")
    builder.line(M.status("补天失败", tone="danger"))
    format_lines(builder, message)
    return builder.build()
