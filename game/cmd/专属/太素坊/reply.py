from game.features.fanben import FanbenFeature, FanbenResult
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


def fanben_result(feature: FanbenFeature, value: FanbenResult) -> DocumentMessage:
    return (
        M.document()
        .header(feature.copy("结算", "标题"))
        .section(value.name, icon="character")
        .line(M.status("返本完成", tone="positive"))
        .row(
            ("原种族", value.race_before),
            ("现种族", M.text(value.race_after, tone="emphasis")),
        )
        .small(
            feature.copy(
                "结算",
                "完成",
                {
                    "人物": value.name,
                    "丹药": value.medicine_name,
                    "原种族": value.race_before,
                    "新种族": value.race_after,
                },
            )
        )
        .build()
    )


def fanben_error(feature: FanbenFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.copy("错误", "标题"), icon="notice")
        .line(M.status("返本失败", tone="danger"), " ", message)
        .build()
    )
