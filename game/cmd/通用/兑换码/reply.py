from typing import Sequence

from game.features.duihuan import DuihuanFeature, DuihuanResult
from message import DocumentMessage, M
from ...actions import CommandAction
from ...presentation import error_document


def result(feature: DuihuanFeature, value: DuihuanResult) -> DocumentMessage:
    return (
        M.document()

        .section(value.name or value.code, icon='reward')
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


def error(
    feature: DuihuanFeature, message: str, actions: Sequence[CommandAction] = ()
) -> DocumentMessage:
    # 统一走 error_document：无 ` / ` 的文案渲染结果与原来相同。
    return error_document(
        feature.copy('错误', '标题'), 'notice', '兑换失败', message, tone='danger',
        actions=actions,
    )