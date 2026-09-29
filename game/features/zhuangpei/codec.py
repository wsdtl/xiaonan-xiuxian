"""稳定装配码：只含槽位、稳定编号和品级，不含用户、范围和时间。"""
import base64
import binascii
from collections.abc import Mapping, Sequence

from .contracts import AssemblyCodeError, Build

SECTIONS = ("功法", "真意", "气机", "器律")
VERSION = 1
MAX_SLOTS = 64
MAX_CODE_LENGTH = 2048


def normalize(build: object) -> Build:
    if not isinstance(build, Mapping) or set(build) != set(SECTIONS):
        raise AssemblyCodeError("方案必须包含功法、真意、气机和器律")
    result: Build = {}
    for section in SECTIONS:
        values = build[section]
        if not isinstance(values, (list, tuple)) or len(values) > MAX_SLOTS:
            raise AssemblyCodeError("装配槽位格式错误")
        rows = []
        for entry in values:
            if entry is None:
                rows.append(None)
                continue
            if not isinstance(entry, Mapping) or set(entry) != {"编号", "品级"}:
                raise AssemblyCodeError("装配条目必须只有编号和品级")
            content_id, grade = entry["编号"], entry["品级"]
            if not isinstance(content_id, str) or len(content_id) != 6 or not content_id.isascii() or not content_id.isdigit() or int(content_id) == 0:
                raise AssemblyCodeError("装配编号必须是六位数字")
            if section == "器律":
                if grade != "":
                    raise AssemblyCodeError("器律不使用品级")
            elif not isinstance(grade, str) or len(grade) != 2 or not grade.isascii() or not grade.isdigit() or int(grade) == 0:
                raise AssemblyCodeError("装配品级必须是两位编号")
            rows.append({"编号": content_id, "品级": grade})
        while rows and rows[-1] is None:
            rows.pop()
        result[section] = tuple(rows)
    return result


def _put(value: int, output: bytearray) -> None:
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)


def encode(build: Mapping[str, Sequence[Mapping[str, str] | None]]) -> str:
    normalized = normalize(build)
    raw = bytearray([VERSION])
    for section, entries in normalized.items():
        raw.append(len(entries))
        for entry in entries:
            _put(0 if entry is None else int(entry["编号"]), raw)
            if entry is not None and section != "器律":
                raw.append(int(entry["品级"]))
    raw.extend(binascii.crc_hqx(raw, 0xFFFF).to_bytes(2, "big"))
    return "ZP1." + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _raw(text: str) -> bytes:
    """解出正文并校验长度与 CRC；任何结构问题都归为"损坏"。"""
    try:
        token = text[4:]
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AssemblyCodeError("装配码格式错误或损坏，请重新复制") from exc
    if len(raw) < 7 or binascii.crc_hqx(raw[:-2], 0xFFFF) != int.from_bytes(raw[-2:], "big"):
        raise AssemblyCodeError("装配码格式错误或损坏，请重新复制")
    return raw


def decode(value: str) -> Build:
    if not isinstance(value, str) or len(value) > MAX_CODE_LENGTH:
        raise AssemblyCodeError("装配码格式错误或过长")
    text = value.strip().rstrip("=")
    if not text.startswith("ZP1."):
        raise AssemblyCodeError("装配码版本不受支持，请重新导出")
    raw = _raw(text)
    if raw[0] != VERSION:
        raise AssemblyCodeError("装配码版本不受支持，请重新导出")
    try:
        position = 1
        result = {}
        for section in SECTIONS:
            count = raw[position]
            position += 1
            if count > MAX_SLOTS:
                raise ValueError("count")
            entries = []
            for _ in range(count):
                number = 0
                for shift in (0, 7, 14):
                    part = raw[position]
                    position += 1
                    number |= (part & 127) << shift
                    if not part & 128:
                        break
                else:
                    raise ValueError("integer")
                if number == 0:
                    entries.append(None)
                    continue
                grade = ""
                if section != "器律":
                    grade = f"{raw[position]:02d}"
                    position += 1
                entries.append({"编号": f"{number:06d}", "品级": grade})
            result[section] = entries
        if position != len(raw) - 2:
            raise ValueError("length")
        normalized = normalize(result)
        if encode(normalized) != text:
            raise ValueError("noncanonical")
        return normalized
    except (ValueError, IndexError, OverflowError, AssemblyCodeError) as exc:
        raise AssemblyCodeError("装配码格式错误或损坏，请重新复制") from exc


__all__ = ["AssemblyCodeError", "SECTIONS", "decode", "encode"]
