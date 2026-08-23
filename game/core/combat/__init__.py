"""第二个公共核心微服务：战斗。"""

from .contracts import (
    BattleEvent as BattleEvent,
)
from .contracts import (
    CombatantReportSpec as CombatantReportSpec,
)
from .contracts import (
    CombatantResult as CombatantResult,
)
from .contracts import (
    CombatantSpec as CombatantSpec,
)
from .contracts import (
    CombatBuildRef as CombatBuildRef,
)
from .contracts import CombatFieldResult as CombatFieldResult
from .contracts import CombatFieldSpec as CombatFieldSpec
from .contracts import CombatFormationResult as CombatFormationResult
from .contracts import CombatFormationSpec as CombatFormationSpec
from .contracts import CombatGroupSpec as CombatGroupSpec
from .contracts import CombatMedicineSpec as CombatMedicineSpec
from .contracts import (
    CombatReportSpec as CombatReportSpec,
)
from .contracts import (
    CombatRequest as CombatRequest,
)
from .contracts import (
    CombatResult as CombatResult,
)
from .contracts import (
    CombatStatus as CombatStatus,
)
from .contracts import (
    CombatStatusSpec as CombatStatusSpec,
)
from .contracts import (
    StatusResult as StatusResult,
)
from .elements import generate_five_elements as generate_five_elements
from .service import CombatService as CombatService

__all__ = [
    "BattleEvent",
    "CombatBuildRef",
    "CombatFieldResult",
    "CombatFieldSpec",
    "CombatFormationResult",
    "CombatFormationSpec",
    "CombatGroupSpec",
    "CombatMedicineSpec",
    "CombatReportSpec",
    "CombatRequest",
    "CombatResult",
    "CombatService",
    "CombatStatus",
    "CombatStatusSpec",
    "CombatantReportSpec",
    "CombatantResult",
    "CombatantSpec",
    "StatusResult",
    "generate_five_elements",
]
