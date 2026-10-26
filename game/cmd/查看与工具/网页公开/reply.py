from game.features.wangye import WangyeFeature
from message import DocumentMessage, M


def notice(feature: WangyeFeature, enabled: bool) -> DocumentMessage:
    """开关回执：状态那行做成一枚分支按钮（点了回二选一菜单，只填入）。"""

    return (
        M.document()

        .section(feature.copy('公开', '标题'), icon='game.spark')
        .line(
            M.command(
                feature.copy('公开', '开启' if enabled else '关闭'),
                '网页资源关闭|网页资源公开',
            )
        )
        .build()
    )


def error(feature: WangyeFeature, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(feature.copy('错误', '标题'), icon='game.pin_doc')
        .line(M.status('没有改成', tone='danger'), ' ', message)
        .build()
    )

