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
from .builds import BUILD_SECTIONS as BUILD_SECTIONS
from .builds import BuildContractError as BuildContractError
from .builds import load_build_contracts as load_build_contracts
from .builds import validate_builds as validate_builds
from .card_text import render_body as render_body
from .card_text import render_listeners as render_listeners
from .service import CombatService as CombatService

__all__ = [
    "BUILD_SECTIONS",
    "BattleEvent",
    "BuildContractError",
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
    "load_build_contracts",
    "render_body",
    "render_listeners",
    "validate_builds",
]
