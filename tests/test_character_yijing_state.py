"""意境存档：旧单路键可迁入「路」，突破不再写回旧键。"""
from __future__ import annotations

import pytest

from game.core.character.contracts import CharacterStateError
from game.core.character.service import _state_yijing


def test_legacy_empty_placeholder_is_ignored() -> None:
    assert _state_yijing({"道行": 3, "编号": "", "阶": 0}) == ({}, 3)


def test_legacy_single_path_is_migrated() -> None:
    assert _state_yijing({"道行": 3, "编号": "630003", "阶": 2}) == (
        {"630003": 2},
        3,
    )


def test_canonical_shape_still_reads() -> None:
    assert _state_yijing({"路": {"630003": 2}, "道行": 3}) == (
        {"630003": 2},
        3,
    )


def test_unknown_key_still_rejected() -> None:
    with pytest.raises(CharacterStateError):
        _state_yijing({"道行": 3, "乱键": 1})
