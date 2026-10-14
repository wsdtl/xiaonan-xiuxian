"""宗门洞天三座生产设施玩法微服务。"""

from .service import SectFacilityFeature, SectFacilityFeatureError
# 命令层不许直接引核心：把「需要挑一件」这个领域结果替它再导出一次（同布阵/炼阵）。
from game.core.formation import FormationChoiceError

__all__ = ["FormationChoiceError", "SectFacilityFeature", "SectFacilityFeatureError"]
