"""非资产战报仓储：按编号存取、过期即不可见、清理按过期与条数双闸。"""
import sqlite3
import time

import pytest

from launch.battle_log import BattleReportStore

NOW = time.time()


def store(tmp_path, *, retention=3600):
    value = BattleReportStore(tmp_path / "runtime_log.db", retention_seconds=retention)
    value.initialize()
    return value


def test_round_trip_and_last_write_wins(tmp_path):
    storage = store(tmp_path)
    storage.save(
        report_id="abc123", kind="切磋", participants=("甲", "乙"),
        finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW, report_json='{"events":[]}',
    )
    first = storage.load("abc123")
    assert first is not None
    assert (first.report_id, first.kind, first.participants) == ("abc123", "切磋", "甲\n乙")
    assert first.report_json == '{"events":[]}'

    storage.save(
        report_id="abc123", kind="宗门战", participants=("甲",),
        finished_at="2026-09-30T11:00:00+08:00", finished_timestamp=NOW + 1, report_json='{"events":[1]}',
    )
    again = storage.load("abc123")
    assert again is not None
    assert (again.kind, again.participants, again.report_json) == ("宗门战", "甲", '{"events":[1]}')


@pytest.mark.parametrize("kind, report_id, report_json", [
    ("不存在", "abc", "{}"),
    ("切磋", "   ", "{}"),
    ("切磋", "abc", "   "),
])
def test_refuses_bad_rows(tmp_path, kind, report_id, report_json):
    storage = store(tmp_path)
    with pytest.raises(ValueError):
        storage.save(
            report_id=report_id, kind=kind, participants=(),
            finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW, report_json=report_json,
        )


def test_expired_report_is_invisible(tmp_path):
    """过期与不存在对外必须表现一致：都回 None，由命令组件决定怎么说。"""
    storage = store(tmp_path, retention=60)
    storage.save(
        report_id="stale", kind="切磋", participants=("甲",),
        finished_at="2026-09-30T10:00:00+08:00",
        finished_timestamp=NOW - 61, report_json="{}",
    )
    assert storage.load("stale") is None
    storage.save(
        report_id="fresh", kind="切磋", participants=("甲",),
        finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW, report_json="{}",
    )
    assert storage.load("fresh") is not None


def test_cleanup_keeps_newest_rows_only(tmp_path):
    storage = store(tmp_path)
    for index in range(5):
        storage.save(
            report_id=f"r{index}", kind="切磋", participants=("甲",),
            finished_at=f"2026-09-30T1{index}:00:00+08:00",
            finished_timestamp=NOW + index, report_json="{}",
        )
    storage.cleanup(now_timestamp=NOW - 1, max_rows=2)
    assert storage.load("r4") is not None and storage.load("r3") is not None
    for gone in ("r0", "r1", "r2"):
        assert storage.load(gone) is None


def test_cleanup_drops_expired_rows(tmp_path):
    storage = store(tmp_path, retention=60)
    storage.save(
        report_id="old", kind="切磋", participants=("甲",),
        finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW - 120, report_json="{}",
    )
    storage.cleanup(now_timestamp=NOW, max_rows=100)
    with sqlite3.connect(tmp_path / "runtime_log.db") as connection:
        left = connection.execute("SELECT COUNT(*) FROM log_battle_reports").fetchone()[0]
    assert left == 0
