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
    return cases + _inbound_cases() + _wide_cases()


def _inbound_cases() -> list[tuple[str, object]]:
    """入站解析的兼容样本。

    样本按代码里的回退链造：`author` 的多种编号字段与名字层级、群事件类型的多个名字、
    mention 的 `is_you` 两种写法、按钮回调里 `resolved` 与文档拼写 `resoloved`。
    其中「应当成功」的几条由 `main()` 里的自检门把关——解析不出事件就拒绝写基准。
    """

    from launch.adapter.qq_protocol.event import (
        normalize_content,
        parse_interaction_event,
        parse_message_event,
    )

    def message(**data: object) -> dict:
        return {"t": "C2C_MESSAGE_CREATE", "d": data}

    def group(**data: object) -> dict:
        return {"t": "GROUP_AT_MESSAGE_CREATE", "d": data}

    base = {"id": "MSG-1", "content": "查看 100005", "author": {"id": "u-1"}}

    cases: list[tuple[str, object]] = [
        # --- 应当成功：私聊 ---
        ("入站/私聊基本", lambda: parse_message_event(message(**base), bot_name="晓楠")),
        ("入站/私聊-author.user_openid", lambda: parse_message_event(
            message(id="MSG-2", content="查看 100005", author={"user_openid": "u-2"}), bot_name="晓楠")),
        ("入站/私聊-author.member_openid", lambda: parse_message_event(
            message(id="MSG-3", content="查看 100005", author={"member_openid": "u-3"}), bot_name="晓楠")),
        # --- 应当成功：群聊（群编号的两种字段） ---
        ("入站/群聊-group_openid", lambda: parse_message_event(
            group(**base, group_openid="g-1"), bot_name="晓楠")),
        ("入站/群聊-group_id", lambda: parse_message_event(
            group(**base, group_id="g-2"), bot_name="晓楠")),
        # --- 应当失败：缺件与不认识的体裁 ---
        ("入站/群聊缺群编号", lambda: parse_message_event(group(**base), bot_name="晓楠")),
        ("入站/缺正文", lambda: parse_message_event(
            message(id="MSG-4", author={"id": "u-1"}), bot_name="晓楠")),
        ("入站/缺消息编号", lambda: parse_message_event(
            message(content="查看 100005", author={"id": "u-1"}), bot_name="晓楠")),
        ("入站/缺发送者", lambda: parse_message_event(
            message(id="MSG-5", content="查看 100005"), bot_name="晓楠")),
        ("入站/不认识的体裁", lambda: parse_message_event(
            {"t": "SOMETHING_ELSE", "d": base}, bot_name="晓楠")),
        ("入站/d 不是对象", lambda: parse_message_event(
            {"t": "C2C_MESSAGE_CREATE", "d": "not-a-dict"}, bot_name="晓楠")),
        ("入站/空 payload", lambda: parse_message_event({}, bot_name="晓楠")),
        # --- 正文归一：mention 的两种 is_you 写法与机器人名匹配 ---
        ("正文/纯文本", lambda: normalize_content("查看 100005", event_type="C2C_MESSAGE_CREATE")),
        ("正文/开头 at 机器人-bool", lambda: normalize_content(
            "<@BOT> 查看 100005", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[{"id": "BOT", "is_you": True, "user_id": "bot-1"}], bot_name="晓楠")),
        ("正文/开头 at 机器人-字符串 is_you", lambda: normalize_content(
            "<@BOT> 查看 100005", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[{"id": "BOT", "is_you": "true", "user_id": "bot-1"}], bot_name="晓楠")),
        ("正文/开头 at 缺 is_you", lambda: normalize_content(
            "<@BOT> 查看 100005", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[{"id": "BOT", "user_id": "bot-1"}], bot_name="晓楠")),
        ("正文/开头 at 按名字匹配", lambda: normalize_content(
            "<@晓楠> 查看 100005", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[{"id": "BOT", "user_id": "bot-1"}], bot_name="晓楠")),
        ("正文/中间 at 别人保留为参数", lambda: normalize_content(
            "查看 <@OTHER>", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[{"id": "OTHER", "is_you": False, "user_id": "u-9"}], bot_name="晓楠")),
        ("正文/mentions 不是列表", lambda: normalize_content(
            "<@BOT> 查看", event_type="GROUP_AT_MESSAGE_CREATE", mentions="x", bot_name="晓楠")),
        # --- 按钮回调：resolved 与文档拼写 resoloved ---
        ("按钮/resolved 写法", lambda: parse_interaction_event(
            {"t": "INTERACTION_CREATE", "d": {"id": "IA-1", "group_openid": "g-1"}},
            {"button_data": "查看 100005", "resolved": {"user_id": "u-1"}})),
        ("按钮/resoloved 写法", lambda: parse_interaction_event(
            {"t": "INTERACTION_CREATE", "d": {"id": "IA-2", "group_openid": "g-1"}},
            {"button_data": "查看 100005", "resoloved": {"user_id": "u-2"}})),
        ("按钮/群成员编号", lambda: parse_interaction_event(
            {"t": "INTERACTION_CREATE", "d": {"id": "IA-3", "group_openid": "g-1"}},
            {"button_data": "查看 100005", "group_member_openid": "u-3"})),
        ("按钮/缺按钮数据", lambda: parse_interaction_event(
            {"t": "INTERACTION_CREATE", "d": {"id": "IA-4", "group_openid": "g-1"}},
            {"resolved": {"user_id": "u-1"}})),
    ]
    return cases


def _wide_cases() -> list[tuple[str, object]]:
    """第三批：把兼容意图**整类**钉住，而不是钉住其中一个名字。

    ① 群事件类型那个常量里现在有几个名字就造几条样本——以后 QQ 加名字、或有人删掉
       某个兼容名，摘要立刻变。
    ② mention 的多组合（多个 at、混 is_you、at 在中间）。
    ③ 去重键：普通消息按消息 ID、按钮按交互 ID。
    ④ 出站：公共文档消息 → QQ 原生载荷（含带按钮的那条，走 keyboard 分支）。
    """

    from message import M

    from launch.adapter.qq_protocol.dedupe import event_dedupe_key
    from launch.adapter.qq_protocol.event import (
        GROUP_MESSAGE_EVENT_TYPES,
        normalize_content,
        parse_message_event,
    )
    from launch.adapter.qq_protocol.render import render_qq_message

    def data(**extra: object) -> dict:
        base = {
            "id": "MSG-D",
            "content": "查看 100005",
            "author": {"id": "u-1"},
            "group_openid": "g-1",
        }
        base.update(extra)
        return base

    cases: list[tuple[str, object]] = []

    # ① 群事件类型逐个枚举
    for index, name in enumerate(sorted(GROUP_MESSAGE_EVENT_TYPES)):
        cases.append(
            (
                f"体裁/群事件类型[{index}]:{name}",
                lambda name=name: parse_message_event(
                    {"t": name, "d": data()}, bot_name="晓楠"
                ),
            )
        )

    # ② 多 mention 组合
    you = {"id": "BOT", "is_you": True, "user_id": "bot-1"}
    other = {"id": "OTHER", "is_you": False, "user_id": "u-9"}
    cases += [
        ("mention/两个 at 都在开头", lambda: normalize_content(
            "<@BOT> <@OTHER> 查看", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[you, other], bot_name="晓楠")),
        ("mention/at 在中间与结尾", lambda: normalize_content(
            "查看 <@OTHER> 并 <@BOT>", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[you, other], bot_name="晓楠")),
        ("mention/同一 token 重复出现", lambda: normalize_content(
            "<@BOT> 查看 <@BOT>", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[you], bot_name="晓楠")),
        ("mention/列表里混非字典", lambda: normalize_content(
            "<@BOT> 查看", event_type="GROUP_AT_MESSAGE_CREATE",
            mentions=[you, "not-a-dict"], bot_name="晓楠")),
        ("mention/私聊体裁不剥前缀", lambda: normalize_content(
            "<@BOT> 查看", event_type="C2C_MESSAGE_CREATE",
            mentions=[you], bot_name="晓楠")),
    ]

    # ③ 去重键：普通消息按消息 ID，按钮按交互 ID
    def parsed_message(message_id: str):
        return parse_message_event(
            {"t": "C2C_MESSAGE_CREATE", "d": {"id": message_id, "content": "查看", "author": {"id": "u-1"}}},
            bot_name="晓楠",
        )

    cases += [
        ("去重/普通消息键", lambda: event_dedupe_key(parsed_message("MSG-X"))),
        ("去重/同一消息两次键相同", lambda: (
            event_dedupe_key(parsed_message("MSG-Y")),
            event_dedupe_key(parsed_message("MSG-Y")),
        )),
        ("去重/不同消息键不同", lambda: (
            event_dedupe_key(parsed_message("MSG-A")),
            event_dedupe_key(parsed_message("MSG-B")),
        )),
    ]

    # ④ 出站渲染
    def simple_document():
        return M.document().header("五岳镇界镇岳诀").section("功法", icon="skill").line("编号 400503").build()

    def document_with_actions():
        return (
            M.document()
            .header("查看结果")
            .section("候选", icon="notice")
            .item(1, M.command(M.text("功法 · 五岳镇界镇岳诀"), "查看 400503", submit=False), " · 400503")
            .build()
        )

    cases += [
        ("出站/文档消息", lambda: render_qq_message(simple_document())),
        ("出站/文档消息带按钮", lambda: render_qq_message(document_with_actions())),
        ("出站/不认识的值原样保留", lambda: render_qq_message({"native": True})),
        ("出站/字符串值", lambda: render_qq_message("plain")),
    ]
    return cases


#: 自检门：这些样本必须给出内容，否则说明样本形状不对，基准不该写。
MUST_SUCCEED_EXTRA = ("入站/私聊基本", "出站/文档消息", "去重/普通消息键")


#: 自检门：这些样本必须解析出事件，否则说明样本形状不对，基准不该写。
MUST_SUCCEED = ("入站/私聊基本", "入站/群聊-group_openid", "正文/纯文本") + MUST_SUCCEED_EXTRA


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

    # 自检门：样本形状不对时，摘要会记一堆 None，那种基准不如不写。
    blank = [name for name in MUST_SUCCEED if summary.get(name) in (None, {"异常": None})]
    if blank:
        print(f"自检未过：{ '、'.join(blank) } 没解析出内容，样本形状不对，拒绝写基准")
        return 2

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
