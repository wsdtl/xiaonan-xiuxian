"""布阵二级组件。"""

from .contracts import FormationArmCopy, FormationArmFeatureError, FormationArmResult
from .service import FormationArmFeature
# 命令层不许直接引核心，所以这里替它把「需要挑一件」这个领域结果再导出一次。
from game.core.formation import FormationChoiceError

__all__ = [
    "FormationChoiceError",
    "FormationArmCopy",
    "FormationArmFeature",
    "FormationArmFeatureError",
    "FormationArmResult",
]
