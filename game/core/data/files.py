"""按 JSON 读取规则注册全部正式数据文件。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .contracts import JsonDataError

ROUTING_RULES_PATH = Path("基础") / "读取规则.json"

OBJECT = "对象"
OBJECT_LIST = "字典列表"
NUMBERED_ENTITY_LIST = "编号实体列表"
NUMBERED_ENTITY_POOL = "编号实体池"
NAMED_ENTITY_POOL = "命名实体池"
NAMED_ENTITY = "命名实体"
ENTITY_ID_POOL = "编号池"
SOURCE_POOL = "源池"

DOCUMENT_SHAPES = frozenset(
    {
        OBJECT,
        OBJECT_LIST,
        NUMBERED_ENTITY_LIST,
        NUMBERED_ENTITY_POOL,
        NAMED_ENTITY_POOL,
        NAMED_ENTITY,
        ENTITY_ID_POOL,
        SOURCE_POOL,
    }
)
ENTITY_SHAPES = frozenset(
    {
        NUMBERED_ENTITY_LIST,
        NUMBERED_ENTITY_POOL,
        NAMED_ENTITY_POOL,
        NAMED_ENTITY,
        ENTITY_ID_POOL,
        SOURCE_POOL,
    }
)


@dataclass(frozen=True)
class ReadRule:
    """一条由 JSON 声明的文件匹配与交付规则。"""

    dataset: str
    pattern: str
    shape: str
    matcher: re.Pattern[str]
    section: str = ""
    number_category: str = ""
    filename_matches_parent: bool = False
    directory_owner_depth: int = 0

    def matches(self, relative_path: str, file_id: str) -> bool:
        if self.matcher.fullmatch(relative_path) is None:
            return False
        parent = relative_path.rsplit("/", 2)[-2] if "/" in relative_path else ""
        return not self.filename_matches_parent or file_id == parent


@dataclass(frozen=True)
class DataReadRules:
    """读取器启动所需的最小 JSON 引导契约。"""

    scan_directories: tuple[str, ...]
    rules: tuple[ReadRule, ...]
    rules_by_scope: MappingProxyType
    number_definition_path: str
    unique_filename_scopes: frozenset[str]
    pool_reference_sections: MappingProxyType

    def descriptor(self, relative_path: str, file_id: str) -> DocumentDescriptor:
        scope = relative_path.partition("/")[0]
        candidates = self.rules_by_scope.get(scope, ())
        matches = tuple(
            rule for rule in candidates if rule.matches(relative_path, file_id)
        )
        if not matches:
            raise JsonDataError(f"数据文件没有匹配的读取规则：{relative_path}")
        if len(matches) > 1:
            patterns = "、".join(rule.pattern for rule in matches)
            raise JsonDataError(f"数据文件匹配多条读取规则：{relative_path} -> {patterns}")
        rule = matches[0]
        directory_owner = ""
        if rule.directory_owner_depth:
            parts = PurePosixPath(relative_path).parts
            directory_owner = parts[-1 - rule.directory_owner_depth]
        return DocumentDescriptor(
            dataset=rule.dataset,
            data_name=file_id,
            shape=rule.shape,
            section=rule.section,
            number_category=rule.number_category,
            source_pool=rule.shape in {NUMBERED_ENTITY_POOL, NAMED_ENTITY_POOL},
            directory_owner=directory_owner,
        )


@dataclass(frozen=True)
class DocumentDescriptor:
    """由读取规则赋予文档的交付身份与通用结构。"""

    dataset: str
    data_name: str
    shape: str
    section: str = ""
    number_category: str = ""
    source_pool: bool = False
    directory_owner: str = ""


@dataclass(frozen=True)
class JsonDocument:
    """一份已经严格解析并匹配读取规则的 JSON 文档。"""

    relative_path: str
    scope: str
    file_id: str
    value: Any
    descriptor: DocumentDescriptor


@dataclass(frozen=True)
class JsonDataCatalog:
    """按路径、数据集和内容文件名注册后的只读文档目录。"""

    documents: tuple[JsonDocument, ...]
    by_path: MappingProxyType
    by_dataset: MappingProxyType
    content_by_file: MappingProxyType
    read_rules: DataReadRules

    def read(self, relative_path: str | Path) -> Any:
        key = _path_key(relative_path)
        document = self.by_path.get(key)
        if document is None:
            raise JsonDataError(f"数据文件没有注册：{relative_path}")
        return document.value

    def dataset(self, name: str) -> tuple[JsonDocument, ...]:
        key = str(name or "").strip()
        if not key:
            raise JsonDataError("数据集名称不能为空")
        documents = self.by_dataset.get(key)
        if documents is None:
            raise JsonDataError(f"数据集不存在：{key}")
        return documents

    def content_file(self, file_id: str) -> JsonDocument:
        key = str(file_id or "").strip().removesuffix(".json").casefold()
        if not key:
            raise JsonDataError("内容文件名不能为空")
        document = self.content_by_file.get(key)
        if document is None:
            raise JsonDataError(f"内容文件不存在：{file_id}.json")
        return document


class JsonDataReader:
    """先读取固定引导文件，再按其中规则解析全部正式 JSON。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    def load_catalog(self) -> JsonDataCatalog:
        read_rules = self._load_read_rules()
        documents: list[JsonDocument] = []
        by_path: dict[str, JsonDocument] = {}
        by_dataset: dict[str, list[JsonDocument]] = {}
        dataset_names: dict[str, dict[str, str]] = {}
        content_by_file: dict[str, JsonDocument] = {}
        content_sources: dict[str, str] = {}
        for scope in read_rules.scan_directories:
            directory = self.root / scope
            if not directory.is_dir():
                raise JsonDataError(f"数据目录不存在：{scope}")
            files = sorted(
                directory.rglob("*.json"),
                key=lambda value: value.relative_to(self.root).as_posix().casefold(),
            )
            for path in files:
                if path == directory / "组件.json":
                    continue
                relative_path = path.relative_to(self.root).as_posix()
                value = self._read_path(path, relative_path)
                descriptor = read_rules.descriptor(relative_path, path.stem)
                document = JsonDocument(
                    relative_path=relative_path,
                    scope=(path.relative_to(directory).parts[0] if path.parent != directory else "定义"),
                    file_id=path.stem,
                    value=value,
                    descriptor=descriptor,
                )
                path_key = relative_path.casefold()
                if path_key in by_path:
                    raise JsonDataError(f"数据文件路径重复：{relative_path}")
                by_path[path_key] = document
                documents.append(document)
                names = dataset_names.setdefault(descriptor.dataset, {})
                previous_name = names.get(descriptor.data_name)
                if previous_name is not None:
                    raise JsonDataError(
                        f"数据集 {descriptor.dataset} 的数据名重复 "
                        f"{descriptor.data_name}：{previous_name} 与 {relative_path}"
                    )
                names[descriptor.data_name] = relative_path
                by_dataset.setdefault(descriptor.dataset, []).append(document)
                if document.scope not in read_rules.unique_filename_scopes:
                    continue
                file_key = path.stem.casefold()
                previous = content_sources.get(file_key)
                if previous is not None:
                    raise JsonDataError(
                        f"内容文件名重复 {path.name}：{previous} 与 {relative_path}"
                    )
                content_sources[file_key] = relative_path
                content_by_file[file_key] = document
        return JsonDataCatalog(
            documents=tuple(documents),
            by_path=MappingProxyType(by_path),
            by_dataset=MappingProxyType(
                {name: tuple(values) for name, values in by_dataset.items()}
            ),
            content_by_file=MappingProxyType(content_by_file),
            read_rules=read_rules,
        )

    def _load_read_rules(self) -> DataReadRules:
        path = self.root / ROUTING_RULES_PATH
        relative_path = ROUTING_RULES_PATH.as_posix()
        value = self._read_path(path, relative_path)
        if not isinstance(value, Mapping):
            raise JsonDataError("读取入口必须是对象")
        if set(value) != {"扫描目录", "编号定义", "文件名唯一", "资源池字段", "归属规则"}:
            raise JsonDataError("读取入口字段错误")
        if any(self.root.glob("*.json")):
            raise JsonDataError("正式 JSON 必须归属组件")
        components = _nonempty_unique_strings(value.get("扫描目录"), "扫描目录")
        actual = {p.name for p in self.root.iterdir() if p.is_dir()}
        if actual != set(components):
            raise JsonDataError(f"组件目录与读取入口不一致：{sorted(actual ^ set(components))}")
        rows = []
        for component in components:
            manifest_path = self.root / component / "组件.json"
            manifest = self._read_path(manifest_path, f"{component}/组件.json")
            if not isinstance(manifest, Mapping) or set(manifest) != {"组件", "读取规则"}:
                raise JsonDataError(f"组件清单字段错误：{component}")
            if manifest["组件"] != component or not _is_array(manifest["读取规则"]):
                raise JsonDataError(f"组件清单身份或规则错误：{component}")
            for row in manifest["读取规则"]:
                if not isinstance(row, Mapping) or not str(row.get("路径", "")).startswith(component + "/"):
                    raise JsonDataError(f"组件不能注册其他组件的文件：{component}")
                parts = PurePosixPath(str(row["路径"])).parts
                if str(row["路径"]) != ROUTING_RULES_PATH.as_posix() and (len(parts) < 3 or parts[1] not in {"定义", "规则", "内容", "展示"}):
                    raise JsonDataError(f"数据必须声明组件内语义分类：{row['路径']}")
                rows.append(row)
        return _parse_read_rules({**value, "读取规则": tuple(rows)}, relative_path)

    @staticmethod
    def _read_path(path: Path, display_path: str) -> Any:
        try:
            text = path.read_text(encoding="utf-8")
            parsed = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
            return _freeze_json(parsed)
        except (OSError, json.JSONDecodeError, JsonDataError) as exc:
            raise JsonDataError(f"数据文件读取失败：{display_path}：{exc}") from exc


def _parse_read_rules(value: Any, path: str) -> DataReadRules:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"数据读取规则根值必须是对象：{path}")
    unknown = set(value) - {
        "扫描目录",
        "编号定义",
        "文件名唯一",
        "资源池字段",
        "归属规则",
        "读取规则",
    }
    if unknown:
        raise JsonDataError(f"数据读取规则存在未知字段：{'、'.join(sorted(unknown))}")
    scopes = _nonempty_unique_strings(value.get("扫描目录"), "扫描目录")
    number_definition_path = _required_string(
        value.get("编号定义"),
        "数据读取规则.编号定义",
    )
    unique_filename_scopes = _declared_scopes(
        value.get("文件名唯一"),
        "文件名唯一",
        ("定义", "规则", "内容", "展示"),
    )
    pool_references = value.get("资源池字段")
    if not isinstance(pool_references, Mapping) or not pool_references:
        raise JsonDataError("读取规则.资源池字段必须是非空对象")
    reference_sections: dict[str, str] = {}
    for key, section in pool_references.items():
        field = str(key or "").strip()
        target = str(section or "").strip()
        if not field.endswith("池") or not target:
            raise JsonDataError("资源池字段必须使用以“池”结尾的字段名和非空实体类别")
        reference_sections[field] = target
    _validate_ownership_rules(value.get("归属规则"))
    rows = value.get("读取规则")
    if not _is_array(rows) or not rows:
        raise JsonDataError("读取规则.读取规则必须是非空字典数组")
    rules: list[ReadRule] = []
    patterns: set[str] = set()
    for index, row in enumerate(rows):
        rule = _parse_read_rule(row, index, scopes)
        if rule.pattern in patterns:
            raise JsonDataError(f"数据读取规则存在重复路径：{rule.pattern}")
        patterns.add(rule.pattern)
        rules.append(rule)
    bootstrap = ROUTING_RULES_PATH.as_posix()
    if sum(rule.matches(bootstrap, ROUTING_RULES_PATH.stem) for rule in rules) != 1:
        raise JsonDataError(f"数据读取规则必须唯一匹配自身：{bootstrap}")
    number_file_id = PurePosixPath(number_definition_path).stem
    if sum(rule.matches(number_definition_path, number_file_id) for rule in rules) != 1:
        raise JsonDataError(f"编号定义必须唯一匹配读取规则：{number_definition_path}")
    by_scope: dict[str, list[ReadRule]] = {scope: [] for scope in scopes}
    for rule in rules:
        by_scope[PurePosixPath(rule.pattern).parts[0]].append(rule)
    return DataReadRules(
        scan_directories=scopes,
        rules=tuple(rules),
        rules_by_scope=MappingProxyType(
            {scope: tuple(values) for scope, values in by_scope.items()}
        ),
        number_definition_path=number_definition_path,
        unique_filename_scopes=unique_filename_scopes,
        pool_reference_sections=MappingProxyType(reference_sections),
    )


def _parse_read_rule(
    value: Any,
    index: int,
    scopes: tuple[str, ...],
) -> ReadRule:
    path = f"数据读取规则.读取规则[{index}]"
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{path}必须是对象")
    allowed = {
        "数据集",
        "路径",
        "结构",
        "实体类别",
        "编号类别",
        "目录主体",
        "归属目录层级",
    }
    unknown = set(value) - allowed
    if unknown:
        raise JsonDataError(f"{path}存在未知字段：{'、'.join(sorted(unknown))}")
    dataset = _required_string(value.get("数据集"), f"{path}.数据集")
    pattern = _required_string(value.get("路径"), f"{path}.路径")
    shape = _required_string(value.get("结构"), f"{path}.结构")
    section = _optional_string(value.get("实体类别"), f"{path}.实体类别")
    number_category = _optional_string(value.get("编号类别"), f"{path}.编号类别")
    filename_matches_parent = _optional_bool(
        value.get("目录主体", False),
        f"{path}.目录主体",
    )
    directory_owner_depth = _optional_nonnegative_int(
        value.get("归属目录层级", 0),
        f"{path}.归属目录层级",
    )
    pattern_path = PurePosixPath(pattern)
    if pattern_path.is_absolute() or ".." in pattern_path.parts:
        raise JsonDataError(f"{path}.路径必须是 data 内相对路径")
    if not pattern.endswith(".json") or not pattern_path.parts:
        raise JsonDataError(f"{path}.路径必须指向 JSON 文件")
    if pattern_path.parts[0] not in scopes:
        raise JsonDataError(f"{path}.路径不属于已声明作用域：{pattern}")
    if any(character in pattern for character in "?[]"):
        raise JsonDataError(f"{path}.路径只允许使用 * 通配符")
    if shape not in DOCUMENT_SHAPES:
        raise JsonDataError(f"{path}.结构不受支持：{shape}")
    if shape in ENTITY_SHAPES and not section:
        raise JsonDataError(f"{path}.实体类别不能为空")
    if shape not in ENTITY_SHAPES and section:
        raise JsonDataError(f"{path}的结构不能声明实体类别")
    if shape in {NUMBERED_ENTITY_LIST, NUMBERED_ENTITY_POOL} and not number_category:
        raise JsonDataError(f"{path}.编号类别不能为空")
    if shape not in {NUMBERED_ENTITY_LIST, NUMBERED_ENTITY_POOL} and number_category:
        raise JsonDataError(f"{path}的结构不能声明编号类别")
    if directory_owner_depth and shape not in ENTITY_SHAPES:
        raise JsonDataError(f"{path}的结构不能声明归属目录层级")
    if directory_owner_depth >= len(pattern_path.parts):
        raise JsonDataError(f"{path}.归属目录层级超出路径深度")
    return ReadRule(
        dataset=dataset,
        pattern=pattern,
        shape=shape,
        matcher=_compile_path_pattern(pattern),
        section=section,
        number_category=number_category,
        filename_matches_parent=filename_matches_parent,
        directory_owner_depth=directory_owner_depth,
    )


def _validate_ownership_rules(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise JsonDataError("读取规则.归属规则必须是对象")
    required = {"地点主体", "地点专属配置", "地点专属内容", "禁止规则"}
    if set(value) != required:
        raise JsonDataError("读取规则.归属规则字段必须完整且不可扩展")
    for key in ("地点主体", "地点专属配置", "地点专属内容"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise JsonDataError(f"读取规则.归属规则.{key}必须是非空字符串")
    forbidden = value.get("禁止规则")
    if not _is_array(forbidden) or not forbidden or any(
        not isinstance(item, str) or not item.strip() for item in forbidden
    ):
        raise JsonDataError("读取规则.归属规则.禁止规则必须是非空字符串数组")


def _nonempty_unique_strings(value: Any, path: str) -> tuple[str, ...]:
    if not _is_array(value) or not value:
        raise JsonDataError(f"数据读取规则.{path}必须是非空字符串数组")
    result = tuple(_required_string(item, f"数据读取规则.{path}") for item in value)
    if len(result) != len(set(result)):
        raise JsonDataError(f"数据读取规则.{path}不能重复")
    if any("/" in item or "\\" in item or item in {".", ".."} for item in result):
        raise JsonDataError(f"数据读取规则.{path}只能包含目录名称")
    return result


def _declared_scopes(
    value: Any,
    path: str,
    scopes: tuple[str, ...],
) -> frozenset[str]:
    result = frozenset(_nonempty_unique_strings(value, path))
    unknown = result - set(scopes)
    if unknown:
        raise JsonDataError(
            f"数据读取规则.{path}包含未声明作用域：{'、'.join(sorted(unknown))}"
        )
    return result


def _required_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonDataError(f"{path}必须是非空字符串")
    return value.strip()


def _optional_string(value: Any, path: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise JsonDataError(f"{path}必须是字符串")
    return value.strip()


def _optional_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise JsonDataError(f"{path}必须是布尔值")
    return value


def _optional_nonnegative_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JsonDataError(f"{path}必须是非负整数")
    return value


def _compile_path_pattern(pattern: str) -> re.Pattern[str]:
    expression = re.escape(pattern).replace(r"\*", "[^/]*")
    return re.compile(expression)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonDataError(f"JSON 对象存在重复键：{key}")
        result[key] = value
    return result


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze_json(raw) for key, raw in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _is_array(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)


def _path_key(relative_path: str | Path) -> str:
    value = Path(str(relative_path or "").strip())
    if value.suffix.lower() != ".json":
        value = value.with_suffix(".json")
    return value.as_posix().casefold()
