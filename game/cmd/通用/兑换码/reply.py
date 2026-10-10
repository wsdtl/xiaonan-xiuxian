from game.features.duihuan import DuihuanFeature, DuihuanResult
from message import DocumentMessage, M


def result(feature: DuihuanFeature, value: DuihuanResult) -> DocumentMessage:
    return (
        M.document()
        .header(feature.copy('兑换', '标题'))
        .section(value.name or value.code, icon='gift')
        .line(M.status('兑换成功', tone='positive'), ' ', M.text(value.code, tone='emphasis'))
        .small(
            feature.copy(
                '兑换',
                '成功',
                {'名称': value.name, '发放': value.granted},
            )
        )
        .build()
    )


def error(feature: DuihuanFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.copy('错误', '标题'), icon='notice')
        .line(M.status('兑换失败', tone='danger'), ' ', message)
        .build()
    )
