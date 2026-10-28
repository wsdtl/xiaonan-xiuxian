from game.features.xigen import XigenFeature, XigenResult
from message import DocumentMessage, M


def xigen_result(feature: XigenFeature, value: XigenResult) -> DocumentMessage:
    return (
        M.document()

        .section(value.name, icon='game.role')
        .line(M.status('洗根完成', tone='positive'))
        .row(
            ('原根性', value.before),
            ('新根性', M.text(value.after, tone='emphasis')),
        )
        .small(
            feature.copy(
                '结算',
                '完成',
                {
                    '人物': value.name,
                    '丹药': value.medicine_name,
                    '原根性': value.before,
                    '新根性': value.after,
                },
            )
        )
        .build()
    )


def xigen_error(feature: XigenFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.copy('错误', '标题'), icon='game.pin_doc')
        .line(M.status('洗根失败', tone='danger'), ' ', message)
        .build()
    )
