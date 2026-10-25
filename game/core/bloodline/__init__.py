"""血脉核心微服务：规则、DNA 生成与匹配。"""

from .dna import breed, random_dna
from .rules import (
    Bloodline,
    BloodlineRules,
    GROUPS,
    awaken_multiplier,
    format_dna,
    load_bloodline_rules,
    matched,
    parse_dna,
)
from .service import BloodlineService, BloodlineStatus

__all__ = [
    "Bloodline",
    "BloodlineRules",
    "BloodlineService",
    "BloodlineStatus",
    "GROUPS",
    "awaken_multiplier",
    "breed",
    "format_dna",
    "load_bloodline_rules",
    "matched",
    "parse_dna",
    "random_dna",
]
