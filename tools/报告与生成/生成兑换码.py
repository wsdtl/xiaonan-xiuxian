'''批量生成兑换码并写进数据文件（运营用，可反复跑）。

码的字母表**刻意去掉容易看错的 0/O、1/I**，免得玩家报码时报错；生成前先与现有码查重，撞了就换一个。
默认只**预演**（打出将要生成的码，不写文件），加 `--write` 才落盘——避免手一滑就往正式数据里塞一百条。

    .venv/Scripts/python.exe -X utf8 tools/报告与生成/生成兑换码.py --count 20 --prefix KAIFU
    .venv/Scripts/python.exe -X utf8 tools/报告与生成/生成兑换码.py --count 20 --prefix KAIFU --write

`--grant` 写成 `类型:参数` 的逗号分隔串：`灵石:1000` 或 `物品:02410137:3`（物品是「指称:数量」，指称＝可选品级前缀＋物品编号＋可选灵宝方括号）。
说明与名称按前缀生成，命名规则改这里就行。
'''

from __future__ import annotations

import argparse
import json
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CODES = ROOT / 'data' / '玩法' / '兑换码' / '内容' / '兑换码.json'
#: 去掉 0/O 与 1/I 的字母表：只留不易看错的字符。
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 10


def _load() -> list[dict]:
    return json.loads(CODES.read_text(encoding='utf-8'))


def _grants(text: str) -> list[dict]:
    out: list[dict] = []
    for piece in (text or '').split(','):
        piece = piece.strip()
        if not piece:
            continue
        parts = piece.split(':')
        kind = parts[0].strip()
        if kind == '灵石':
            out.append({'类型': '灵石', '数量': int(parts[1])})
        elif kind == '物品':
            # 统一语法：指称一段（可选品级前缀＋物品编号＋可选灵宝方括号），数量是后面独立的一段。
            from game.core.asset import parse_item_ref

            ref = parse_item_ref(parts[1].strip())
            item = {'类型': '物品', '编号': ref.item, '数量': int(parts[-1])}
            if ref.grade:
                item['品级'] = ref.grade
            out.append(item)
        else:
            raise SystemExit(f'不认识的发放类型：{kind}（只支持 灵石 与 物品）')
    if not out:
        raise SystemExit('发放清单是空的')
    return out


def _next_id(rows: list[dict]) -> str:
    used = {int(str(row.get('编号'))[2:]) for row in rows if str(row.get('编号', '')).isdigit()}
    flow = 1
    while flow in used:
        flow += 1
    return '64%04d' % flow


def main() -> int:
    parser = argparse.ArgumentParser(description='批量生成兑换码')
    parser.add_argument('--count', type=int, default=1)
    parser.add_argument('--prefix', default='XIAONAN')
    parser.add_argument('--grant', default='灵石:1000')
    parser.add_argument('--limit', type=int, default=1, help='每人限次')
    parser.add_argument('--name', default='', help='名称（默认按前缀与序号给）')
    parser.add_argument('--write', action='store_true', help='真的写进数据文件')
    args = parser.parse_args()
    if args.count < 1 or args.count > 500:
        raise SystemExit('一次生成 1 到 500 条')
    rows = _load()
    taken = {str(row.get('码') or '').upper() for row in rows}
    grants = _grants(args.grant)
    made: list[dict] = []
    for index in range(args.count):
        while True:
            code = args.prefix.upper() + ''.join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            if code not in taken:
                break
        taken.add(code)
        name = args.name or f'{args.prefix}礼包{index + 1}'
        made.append({
            '编号': _next_id(rows + made),
            '名称': name,
            '说明': f'{name}：{args.grant}。',
            '码': code,
            '发放': [dict(item) for item in grants],
            '每人限次': args.limit,
        })
    for row in made:
        print('   %s  %s' % (row['编号'], row['码']))
    if not args.write:
        print(f'（预演：{len(made)} 条，没有写文件；加 --write 才落盘）')
        return 0
    CODES.write_text(json.dumps(rows + made, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')
    print(f'已写入 {len(made)} 条到 {CODES.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
