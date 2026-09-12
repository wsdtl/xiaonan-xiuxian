"""协议适配对照：把 QQ 适配层的纯函数行为做成可比对的摘要。

`launch/adapter/` 是「外面的世界 ↔ 游戏」的翻译口：入站把 QQ 报文归一成事件，出站把
公共消息翻成 QQ 原生协议，中间还有签名校验、去重、发送目标。这一层**没有任何判据**，
而它最容易被悄悄改坏的恰恰是那些看起来没用的兼容分支——砍掉不会有任何报错，只是某类
消息从此不响应。

**它不是「真实语料回归」**：仓库里没有真实报文样本，所以样本是按协议形状与代码里的兼容
分支造的。它冻住的是「每个分支现在什么行为」，不是「真实流量下什么行为」。

    .venv/Scripts/python.exe -X utf8 tools/协议适配对照.py            # 与入库基准对照
    .venv/Scripts/python.exe -X utf8 tools/协议适配对照.py --写基准    # 重新取基准

每一例都单独 try/except，**异常类型与文案也进摘要**——拒绝行为同样是要冻住的行为。

**退出码约定（与另六条通道一致）：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "协议适配摘要.json"

#: 固定的签名密钥、时间戳与「现在」，让签名类样本可复现。
SECRET = "判据用密钥-not-a-real-secret"
STAMP = "1767225600"
NOW = 1767225600.0
BODY = b'{"op":0,"d":{"id":"MSG-1","content":"\\u67e5\\u770b 100005"}}'


def _canonical(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if hasattr(value, "pattern"):  # 正则一类
        return f"<{type(value).__name__}:{value.pattern}>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__name__}>"


def _cases() -> list[tuple[str, object]]:
    """产出 (样本名, 无参可调用)。每个可调用返回待摘要的值，抛错也会被记下来。"""

    from launch.adapter.qq_protocol import payload
    from launch.adapter.qq_protocol.target import qq_group_target, qq_private_target
    from launch.adapter.qq_wh import signature

    cases: list[tuple[str, object]] = [
        # --- 签名：确定性、校验通过、篡改被拒、过期被拒 ---
        ("签名/验证签名", lambda: signature.make_validation_signature(SECRET, "token-1", STAMP)),
        ("签名/事件签名", lambda: signature.make_event_signature(SECRET, STAMP, BODY)),
        ("签名/校验通过", lambda: signature.verify_event_signature(
            SECRET, STAMP, BODY, signature.make_event_signature(SECRET, STAMP, BODY), now=NOW
        )),
        ("签名/正文被改", lambda: signature.verify_event_signature(
            SECRET, STAMP, BODY + b" ", signature.make_event_signature(SECRET, STAMP, BODY), now=NOW
        )),
        ("签名/时间过期", lambda: signature.verify_event_signature(
            SECRET, STAMP, BODY, signature.make_event_signature(SECRET, STAMP, BODY),
            now=NOW + 3600,
        )),
        ("签名/签名本身乱写", lambda: signature.verify_event_signature(
            SECRET, STAMP, BODY, "not-a-signature", now=NOW
        )),
        # --- 发送目标 ---
        ("目标/私聊", lambda: qq_private_target("u-1")),
        ("目标/私聊唤醒", lambda: qq_private_target("u-1", is_wakeup=True)),
        ("目标/群聊", lambda: qq_group_target("g-1")),
        ("目标/群聊带用户", lambda: qq_group_target("g-1", user_id="u-1")),
        ("目标/私聊空编号", lambda: qq_private_target("")),
        ("目标/群聊空编号", lambda: qq_group_target("")),
        # --- 出站载荷构造 ---
        ("载荷/文本", lambda: payload.text("你好")),
        ("载荷/文本带额外字段", lambda: payload.text("你好", msg_seq=7)),
        ("载荷/Markdown", lambda: payload.markdown("# 标题", custom_template_id="t-1")),
        ("载荷/Ark", lambda: payload.ark({"app": "x"})),
        ("载荷/Embed", lambda: payload.embed({"title": "x"})),
        ("载荷/媒体字符串", lambda: payload.media("file_info-1")),
        ("载荷/媒体对象", lambda: payload.media({"file_uuid": "f-1"})),
        ("载荷/图片", lambda: payload.image("base64-abc")),
        ("载荷/原始", lambda: payload.raw({"content": "x", "msg_type": 0})),
    ]
    return cases


def digest() -> tuple[dict[str, object], list[str]]:
    summary: dict[str, object] = {}
    failures: list[str] = []
    for name, case in _cases():
        try:
            summary[name] = _canonical(case())
        except Exception as exc:  # noqa: BLE001 - 拒绝行为也要冻住
            summary[name] = {"异常": f"{type(exc).__name__}: {exc}"}
            failures.append(f"{name}：{type(exc).__name__}: {exc}")
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE), help="入库基准摘要")
    parser.add_argument("--写基准", action="store_true", help="把当前摘要写进 --基准")
    args = parser.parse_args()

    summary, raised = digest()
    print(f"{len(summary)} 例，其中抛错 {len(raised)} 例（抛错也会进摘要）")
    for line in raised[:10]:
        print(f"  {line}")

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {baseline}")
        return 0

    if not baseline.is_file():
        print(f"基准不存在：{baseline}；先跑一次 --写基准")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基准无法读取：{exc}")
        return 2

    changed = sorted(
        key for key in summary.keys() & expected.keys() if summary[key] != expected[key]
    )
    added = sorted(summary.keys() - expected.keys())
    missing = sorted(expected.keys() - summary.keys())
    same = len(summary.keys() & expected.keys()) - len(changed)
    print(
        f"对照 {baseline}（{len(expected)} 例）：一致 {same} / {len(summary)}"
        f" · 差异 {len(changed)} · 新增 {len(added)} · 缺失 {len(missing)}"
    )
    for key in changed:
        print(f"  [差异] {key}")
        print(f"      - {json.dumps(expected[key], ensure_ascii=False)[:160]}")
        print(f"      + {json.dumps(summary[key], ensure_ascii=False)[:160]}")
    for key in added:
        print(f"  [新增] {key}")
    for key in missing:
        print(f"  [缺失] {key}")
    return 1 if (changed or added or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
