from game.features.butian import ButianFeature, ButianResult
from message import DocumentMessage, M
from ...presentation import error_document


def result(feature: ButianFeature, value: ButianResult) -> DocumentMessage:
    return (
        M.document()

        .section(value.target_name, icon="game.manual")
        .line(M.status("补天完成", tone="positive"))
        .field("补正境界", value.realm_name)
        .field(value.attribute, M.text(value.value, tone="cultivation"))
        .small(feature.copy("结算", "完成"))
        .build()
    )


def error(feature: ButianFeature, message: str) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        feature.copy("错误", "标题"), "game.pin_doc", "补天失败", message, tone="danger"
    )
