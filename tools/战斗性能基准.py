"""固定 15v15；旧基准每人 18 功法，--suite666 测每人 6 功法/6 真意/6 气机。

python -X utf8 tools/战斗性能基准.py --scene original --runs 5
python -X utf8 tools/战斗性能基准.py --scene chain --runs 5 --report

不计服务启动、结果校验序列化和网络发送。--report 另包含战报构建。
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
import random
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger
import game.app as app
from main import create_app
from game.core.combat.contracts import CombatantSpec, CombatBuildRef, CombatRequest, CombatReportSpec

ATTRIBUTES = {
    '血气上限': 1200, '精神上限': 400, '攻击': 150, '防御': 60, '速度': 110,
    '命中率': 100, '闪避率': 5, '暴击率': 20, '抗暴率': 5, '暴击伤害': 150,
    '格挡率': 10, '破格率': 5, '格挡减伤': 30, '伤害加成': 100, '伤害减免': 0,
}


def fingerprint(value):
    serialized = json.dumps(asdict(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()


def request_for(scene, seed, report):
    cards = [str(number) for number in range(400541, 400559)] if scene == 'original' else [str(number) for number in range(400001, 400019)]
    teams = []
    for side in ('L', 'R'):
        team = []
        for index in range(15):
            identity = f'{side}{index:02}' if scene == 'original' else f'{side}{index}'
            team.append(CombatantSpec(
                id=identity, name=identity, attributes=dict(ATTRIBUTES),
                build=tuple(CombatBuildRef(
                    '功法', card, born_order=order,
                    instance_id=f'{side}{index}:{card}' if scene == 'original' else f'{side}{index}:{order}',
                ) for order, card in enumerate(cards)),
            ))
        teams.append(tuple(team))
    return CombatRequest(
        left_team=teams[0], right_team=teams[1], seed=seed, action_limit=2400,
        report=CombatReportSpec(generated_at='2026-09-25T00:00:00') if report else None,
    )


def mixed_request(core, scene, build_seed, battle_seed):
    """均匀抽样合法混装；连锁场景从高频事件联动家族抽样并镜像满编。"""
    catalog = {}
    for category in ('功法', '真意', '气机'):
        catalog[category] = [
            (str(row['编号']), path.stem)
            for path in sorted((ROOT / 'data' / '战斗' / '内容' / category).glob(f'{category}-*.json'))
            for row in json.loads(path.read_text(encoding='utf-8'))
        ]
    pools = {category: [identity for identity, _ in rows] for category, rows in catalog.items()}
    if scene == 'chain666':
        pools['功法'] = [str(value) for value in range(400001, 400019)]
        pools['真意'] = [identity for identity, family in catalog['真意']
                         if family in {'真意-返照', '真意-生灭', '真意-同契', '真意-众生', '真意-状态'}]
    rng = random.Random(build_seed)
    def sample():
        for _ in range(10000):
            selected = {category: rng.sample(pool, 6) for category, pool in pools.items()}
            if core.growth.build_conflict(selected) is None:
                return selected
        raise RuntimeError('未找到合法 666 构筑')
    shared = sample() if scene == 'chain666' else None
    teams = []
    for side in ('L', 'R'):
        team = []
        for index in range(15):
            selected = shared if shared is not None else sample()
            identity = f'{side}{index:02}'
            refs = tuple(CombatBuildRef(category, card, instance_id=f'{identity}:{category}:{card}', born_order=order)
                         for category, cards in selected.items() for order, card in enumerate(cards))
            team.append(CombatantSpec(id=identity, name=identity, attributes=dict(ATTRIBUTES), build=refs))
        teams.append(tuple(team))
    return CombatRequest(left_team=teams[0], right_team=teams[1], seed=battle_seed, action_limit=2400,
                         report=CombatReportSpec(generated_at='2026-09-26T00:00:00'))


def suite666(core, path):
    """逐进程隔离 18 组；45 秒为整组时限，计时仍只测 execute。"""
    output = dict(protocol='15v15-666-v1', cases=[], process_timeout_seconds=45)
    path.parent.mkdir(parents=True, exist_ok=True)
    case_dir = path.parent / (path.stem + '-cases')
    case_dir.mkdir(exist_ok=True)
    def save():
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    def run_case(scene, build_seed, seed, runs=1):
        key = f'{scene}-{build_seed}-{seed}-runs{runs}'
        case_path = case_dir / f'{key}.json'
        command = [sys.executable, '-X', 'utf8', str(Path(__file__).resolve()),
                   '--scene', scene, '--build-seed', str(build_seed), '--seed', str(seed),
                   '--runs', str(runs), '--report', '--verify', '--output', str(case_path.resolve())]
        with case_path.with_suffix('.log').open('w', encoding='utf8') as log:
            try:
                result = subprocess.run(command, stdout=log, stderr=log, cwd=ROOT, timeout=45 if runs == 1 else 180)
                status = 'complete' if result.returncode == 0 else 'error'
            except subprocess.TimeoutExpired:
                status = 'timeout'
        row = dict(case=key, scene=scene, build_seed=build_seed, seed=seed, status=status)
        if case_path.exists():
            row['result'] = json.loads(case_path.read_text(encoding='utf8'))
        row['log'] = str(case_path.with_suffix('.log'))
        return row
    for scene in ('mixed666', 'chain666'):
        for build_seed in (20260926, 20260927, 20260928):
            for seed in (20260911, 20260912, 20260913):
                row = run_case(scene, build_seed, seed)
                output['cases'].append(row)
                save()
                print(json.dumps(row, ensure_ascii=False), flush=True)
    completed = [row for row in output['cases'] if row['status'] == 'complete']
    if completed:
        worst = max(completed, key=lambda row: row['result']['median_seconds'])
        output['worst_repeat'] = run_case(worst['scene'], worst['build_seed'], worst['seed'], 5)
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', choices=('original', 'chain', 'mixed666', 'chain666'), default='original')
    parser.add_argument('--build-seed', type=int, default=20260926)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--seed', type=int, default=20260911)
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--verify', action='store_true', help='计时结束后，对照完整轨迹与战报模式的全部结算字段')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--suite666', action='store_true', help='18 组合法 666 混装筛查、完整结算对照及最慢组五次复测')
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be positive')
    logger.remove()
    create_app()
    logger.remove()
    with tempfile.TemporaryDirectory() as directory:
        original_config = app.game_config
        app.game_config = replace(original_config, database=replace(original_config.database, path=Path(directory) / 'game.db'))
        built = app.build_game_services(data_dir=ROOT / 'data')
        try:
            if args.suite666:
                suite666(built.core, args.output or ROOT / '_输出/combat-performance/stress666.json')
                return
            if args.scene in ('mixed666', 'chain666'):
                request = mixed_request(built.core, args.scene, args.build_seed, args.seed)
                if not args.report:
                    request = replace(request, report=None)
            else:
                request = request_for(args.scene, args.seed, args.report)
            path = args.output or ROOT / '_输出' / 'combat-performance' / f'final-{args.scene}-{args.report}.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix('.request.json').write_text(json.dumps(asdict(request), ensure_ascii=False, indent=2), encoding='utf8')
            progress_path = path.with_suffix('.progress.json')
            runs = []
            def progress(stage):
                progress_path.write_text(json.dumps(dict(stage=stage, request_sha256=fingerprint(request), runs=runs), ensure_ascii=False, indent=2), encoding='utf8')
            for index in range(args.runs):
                progress('simulation')
                start = time.perf_counter()
                result = asyncio.run(built.core.combat.execute(request))
                seconds = time.perf_counter() - start
                row = dict(run=index + 1, seconds=seconds, result_sha256=fingerprint(result),
                           actions=result.actions, total_events=result.total_event_count,
                           captured_events=len(result.events), activations=result.trigger_activations)
                runs.append(row)
                progress('measured')
                print(json.dumps(row), flush=True)
            if len({row['result_sha256'] for row in runs}) != 1:
                raise RuntimeError('同一请求的完整结果发生变化')
            verification = None
            if args.verify:
                progress('full_trace_verification')
                counterpart = asyncio.run(built.core.combat.execute(replace(
                    request, report=None if args.report else CombatReportSpec(generated_at='2026-09-25T00:00:00'),
                )))
                full, reported = (counterpart, result) if args.report else (result, counterpart)
                def settlement(value):
                    return replace(value, events=(), report=None, presentation=None)
                if settlement(full) != settlement(reported):
                    raise RuntimeError('战报压缩改变了结算结果')
                verification = dict(settlement_equal=True, full_result_sha256=fingerprint(full),
                                    full_events=len(full.events), reported_events=len(reported.events))
            output = dict(scene=args.scene, report=args.report, seed=args.seed,
                          build_seed=args.build_seed if args.scene.endswith('666') else None,
                          verification=verification,
                          request_sha256=fingerprint(request), python=sys.version,
                          runs=runs, median_seconds=statistics.median(row['seconds'] for row in runs),
                          minimum_seconds=min(row['seconds'] for row in runs),
                          maximum_seconds=max(row['seconds'] for row in runs))
            path = args.output or ROOT / '_输出' / 'combat-performance' / f'final-{args.scene}-{args.report}.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
            progress('complete')
            print(json.dumps(output, ensure_ascii=False), flush=True)
        finally:
            built.core.database.close()
            app.game_config = original_config


if __name__ == '__main__':
    main()
