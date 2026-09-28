from game.features.yixing import YixingFeature, YixingResult
from message import DocumentMessage, M


def result(feature: YixingFeature, value: YixingResult) -> DocumentMessage:
    return (
        M.document()
        .header(feature.copy("结算", "标题"))
        .section(value.name, icon="character")
        .line(M.status("易形完成", tone="positive"))
        .row(
            ("原性别", value.gender_before),
            ("现性别", M.text(value.gender_after, tone="emphasis")),
        )
        .small(feature.copy("结算", "完成"))
        .build()
    )


def error(feature: YixingFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.copy("错误", "标题"), icon="notice")
        .line(M.status("易形失败", tone="danger"), " ", message)
        .build()
    )
