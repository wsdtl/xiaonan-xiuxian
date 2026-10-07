"""跑单元测试：把 tests/ 拆成耗时相近的若干片并发跑，缩短墙钟。

两份浪费要收掉：① 各文件都要单独装一遍数据快照，串行跑是纯浪费；② 单文件也能
很贵（`test_component_loading.py` 一个文件就 20 秒），独占一片会把墙钟锁死在它身上。
所以超过阈值的文件**按用例再拆**，分组用实测耗时做 LPT。

    .venv/Scripts/python.exe -X utf8 tools/跑测试.py

**退出码：0 = 全部通过，1 = 有失败。**
"""
from __future__ import annotations

import concurrent.futures
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
GROUPS = max(1, min(8, os.cpu_count() or 4))

#: 实测的每文件耗时（秒），用来做 LPT 平衡分组——按文件大小分会严重失衡。
#: 刷新方式：对每个 `tests/test_*.py` 单独计时。
WEIGHTS: dict[str, float] = {
    "test_component_loading.py": 20.7,
    "test_action_group_common_actions.py": 18.6,
    "test_alchemy_missing_guidance.py": 11.5,
    "test_data_contract.py": 10.2,
    "test_zhuangpei.py": 7.1,
    "test_prepared_status.py": 6.7,
    "test_lingtian_terrain.py": 6.7,
    "test_breakthrough_medicine_source.py": 6.0,
    "test_zhuangpei_site.py": 5.3,
    "test_combat_entry_surfaces.py": 5.1,
    "test_enemy_and_raid.py": 4.0,
    "test_cangjing_borrow_invalidation.py": 3.9,
    "test_inherent_rules.py": 3.6,
    "test_race_registry.py": 3.5,
    "test_battle_report_site.py": 3.4,
    "test_build_templates.py": 2.7,
    "test_lingcang_take_wiring.py": 2.7,
    "test_term_naming.py": 2.4,
    "test_command_minimal_signatures.py": 2.0,
    "test_qiecuo_report_link.py": 2.0,
    "test_battle_report_store.py": 1.9,
    "test_zhuangpei_codec.py": 1.8,
    "test_exploration_groups.py": 1.7,
    "test_battle_report_assets.py": 1.7,
    "test_attribute_calibers.py": 1.7,
}
#: 权重表里没有的新文件按这个估——宁可略高，别让它把一片拖长。
DEFAULT_WEIGHT = 3.0
#: 耗时超过这个值的文件按用例拆开，不让一个文件独占一片。
SPLIT_THRESHOLD = 10.0
#: 拆成几份。
SPLIT_PARTS = 3


def _collect(path: pathlib.Path) -> list[str]:
    """取一个测试文件的用例 node id，用来把它拆开跑。"""

    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "--collect-only", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip() for line in (done.stdout or "").splitlines() if "::" in line]


def _units() -> list[tuple[float, list[str]]]:
    """把测试拆成「权重 + 一组 pytest 参数」的工作单元。"""

    units: list[tuple[float, list[str]]] = []
    for path in sorted(TESTS.glob("test_*.py")):
        weight = WEIGHTS.get(path.name, DEFAULT_WEIGHT)
        relative = f"tests/{path.name}"
        if weight <= SPLIT_THRESHOLD:
            units.append((weight, [relative]))
            continue
        node_ids = _collect(path)
        if len(node_ids) < SPLIT_PARTS:
            units.append((weight, [relative]))
            continue
        for part in (node_ids[index::SPLIT_PARTS] for index in range(SPLIT_PARTS)):
            units.append((weight / SPLIT_PARTS, part))
    return units


def _shards() -> list[list[str]]:
    """按权重做 LPT 平衡分组，让墙钟逼近最大单片。"""

    groups: list[list[str]] = [[] for _ in range(GROUPS)]
    load = [0.0] * GROUPS
    for weight, args in sorted(_units(), key=lambda unit: -unit[0]):
        slot = load.index(min(load))
        groups[slot].extend(args)
        load[slot] += weight
    return [group for group in groups if group]


def _run(job: tuple[int, list[str]]) -> tuple[bool, str, float]:
    index, args = job
    started = time.perf_counter()
    # 本环境的 TEMP/TMP 没设，pytest 与 tempfile 会回落到当前工作目录，把
    # pytest-of-* 与临时库落在仓库根。显式指到 _输出/ 下（已被 .gitignore 忽略）。
    basetemp = ROOT / "_输出" / "测试临时" / f"片{index}"
    basetemp.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(basetemp), "TMP": str(basetemp)}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "--basetemp", str(basetemp), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = ""
    for line in reversed((done.stdout or "").splitlines()):
        if line.strip():
            tail = line.strip()
            break
    return done.returncode == 0, tail[:120], time.perf_counter() - started


def main() -> int:
    groups = _shards()
    started = time.perf_counter()
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(groups)) as pool:
        for index, (ok, tail, seconds) in enumerate(pool.map(_run, enumerate(groups, start=1)), start=1):
            print(f"  [{'通过' if ok else '失败'}] 第 {index} 组（{len(groups[index - 1])} 个单元） {seconds:>6.1f}s  {tail}")
            if not ok:
                failures.append(str(index))
    wall = time.perf_counter() - started
    if failures:
        print(f"单元测试：{len(groups)} 组，失败 {len(failures)} 组 —— 第 {'、'.join(failures)} 组（墙钟 {wall:.1f}s）")
        return 1
    print(f"单元测试：{len(groups)} 组全部通过（墙钟 {wall:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
