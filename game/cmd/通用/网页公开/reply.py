from game.features.wangye import WangyeFeature
from message import DocumentMessage, M


def notice(feature: WangyeFeature, enabled: bool) -> DocumentMessage:
    return (
        M.document()
        .header(feature.copy('公开', '标题'))
        .line(M.status('已公开' if enabled else '已关闭', tone='positive' if enabled else 'notice'))
        .small(feature.copy('公开', '开启' if enabled else '关闭'))
        .build()
    )


def error(feature: WangyeFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.copy('错误', '标题'), icon='notice')
        .line(M.status('没有改成', tone='danger'), ' ', message)
        .build()
    )

