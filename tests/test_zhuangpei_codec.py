"""装配码协议：稳定、无身份、损坏拒绝，槽位语义不可丢。"""
import base64
import binascii
import random

import pytest

from game.features.zhuangpei.codec import AssemblyCodeError, decode, encode, normalize

def empty():
    return {"功法": [], "真意": [], "气机": [], "器律": []}


def test_stable_content_only_and_preserves_holes():
    build = empty()
    build["功法"] = [None, {"编号": "400001", "品级": "02"}, None]
    code = encode(build)
    assert decode(code)["功法"] == (None, {"编号": "400001", "品级": "02"})
    assert encode(dict(reversed(list(build.items())))) == code
    build["功法"].pop()
    assert encode(build) == code
    build["功法"].reverse()
    assert encode(build) != code
    assert encode(empty()) == encode(decode(encode(empty())))


def test_randomized_roundtrip():
    rng = random.Random(20260929)
    for _ in range(200):
        build = {s: [None if rng.random() < .3 else {"编号": f"{rng.randrange(1, 999999):06d}", "品级": "" if s == "器律" else f"{rng.randrange(1, 10):02d}"} for _ in range(rng.randrange(9))] for s in empty()}
        assert decode(encode(build)) == normalize(build)


@pytest.mark.parametrize("value", ["ZP0.invalid", "ZP1.", "ZP1.@@@", "x"*3000, "", None, 12, "ZP1.AAAAAAA="])
def test_invalid_codes(value):
    with pytest.raises(AssemblyCodeError):
        decode(value)


def test_damage_rejected():
    code = encode(empty())
    replacement = "A" if code[-1] != "A" else "B"
    with pytest.raises(AssemblyCodeError):
        decode(code[:-1] + replacement)


@pytest.mark.parametrize("entry", [
    {"编号": "000000", "品级": "01"}, {"编号": "400001", "品级": "黄"},
    {"编号": "400001", "品级": "00"}, {"编号": 400001, "品级": "01"},
    {"编号": "400001", "品级": "01", "用户": "A"}, {"编号": "４００００１", "品级": "01"},
    {"编号": "400001"}, "400001", True,
])
def test_bad_entries(entry):
    build = empty()
    build["功法"] = [entry]
    with pytest.raises(AssemblyCodeError):
        encode(build)


def test_structure_bounds():
    for build in ({}, {**empty(), "scope": "all"}, {**empty(), "功法": [None]*65}, {**empty(), "功法": "x"},
                  {**empty(), "器律": [{"编号": "700001", "品级": "01"}]}):
        with pytest.raises(AssemblyCodeError):
            encode(build)


def craft(body: bytes) -> str:
    """按协议手搓一份带正确 CRC 的码，用来打解码器内部的分支。"""
    raw = bytes(body) + binascii.crc_hqx(bytes(body), 0xFFFF).to_bytes(2, "big")
    return "ZP1." + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_inner_version_byte_reports_version_error():
    """外层前缀对、内层版本号不对 ⇒ 说"版本不受支持"，不能说"损坏"。"""
    with pytest.raises(AssemblyCodeError, match="版本"):
        decode(craft(bytes([2, 0, 0, 0, 0])))


def test_crafted_payloads_rejected():
    for body in (
        bytes([1, 65, 0, 0, 0]),                       # 槽位数超过上限
        bytes([1, 1, 0x80, 0x80, 0x80, 0x00, 0, 0, 0]),  # 变长整数用了四字节
        bytes([1, 0, 0, 0, 0, 7]),                     # 尾部多余字节
        bytes([1]),                                    # 正文过短
    ):
        with pytest.raises(AssemblyCodeError):
            decode(craft(body))


def test_whitespace_and_padding_tolerated():
    """从聊天里复制来的码常带首尾空白或 base64 补位，都要认。"""
    code = encode(empty())
    assert decode("  " + code + "\n") == decode(code)
    assert decode(code + "=" * (-len(code) % 4)) == decode(code)

