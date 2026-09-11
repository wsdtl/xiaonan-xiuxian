"""One-shot, collision-checked migration of the current data tree."""

import hashlib
import json
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
KINDS = ("定义", "规则", "内容", "展示")


def destination(path):
    parts = path.split("/")
    kind = parts[0]
    if len(parts) == 2:
        return "基础/" + ("" if parts[1] == "读取规则.json" else kind + "/") + parts[1]
    domain, *rest = parts[1:]
    if domain == "玩法":
        if rest == ["说明.md"]:
            return "基础/规则/玩法说明.md"
        domain = Path(rest[0]).stem
    if domain in ("功法", "真意", "气机", "战斗机制", "战场环境", "构筑"):
        return "/".join(("战斗", kind, domain, *rest))
    if domain in ("万珍殿", "灵藏", "藏经阁", "山门", "宗门同行", "宗门战", "宗门生产", "宗门设施"):
        return "/".join(("宗门", kind, domain, *rest))
    domain = {"炼药": "炼丹", "纳戒": "基础物品", "人物培养": "培养", "道侣培养": "培养"}.get(domain, domain)
    return "/".join((domain, kind, *rest))


def main():
    bootstrap = DATA / "定义/读取规则.json"
    recovering = not bootstrap.exists()
    old_rules = json.loads((DATA / "基础/读取规则.json" if recovering else bootstrap).read_text(encoding="utf-8"))
    sources = sorted(p for kind in KINDS for p in (DATA / kind).rglob("*") if p.is_file())
    mapping = {p.relative_to(DATA).as_posix(): destination(p.relative_to(DATA).as_posix()) for p in sources}
    if recovering:
        tracked = subprocess.check_output(["git", "ls-files", "-z", "data"], cwd=ROOT).decode("utf-8").split("\0")
        mapping = {p[5:]: destination(p[5:]) for p in tracked if p.startswith(tuple("data/" + k + "/" for k in KINDS))}
    if len(set(mapping.values())) != len(mapping):
        raise RuntimeError("Migration target collision")
    for target in mapping.values():
        resolved = (DATA / target).resolve()
        if not resolved.is_relative_to(DATA.resolve()) or (resolved.exists() and not recovering):
            raise RuntimeError(f"Unsafe migration target: {resolved}")
    hashes = {old: hashlib.sha256((DATA / (mapping[old] if recovering else old)).read_bytes()).hexdigest() for old in mapping if old.endswith(".json") and old != "定义/读取规则.json"}
    manifests = {}
    for row in old_rules.pop("读取规则"):
        if row["路径"].startswith("规则/玩法/") and "*" in row["路径"]:
            matcher = re.compile(re.escape(row["路径"]).replace(r"\*", "[^/]*"))
            for old in mapping:
                if matcher.fullmatch(old):
                    new = destination(old)
                    manifests.setdefault(new.split("/")[0], []).append({**row, "路径": new})
            continue
        row["路径"] = destination(row["路径"])
        component = row["路径"].split("/")[0]
        manifests.setdefault(component, []).append(row)
    for old, new in mapping.items():
        target = DATA / new
        target.parent.mkdir(parents=True, exist_ok=True)
        if not recovering:
            (DATA / old).rename(target)
    for old, digest in hashes.items():
        if hashlib.sha256((DATA / mapping[old]).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Data changed during migration: {old}")
    for component, rows in manifests.items():
        (DATA / component / "组件.json").write_text(json.dumps({"组件": component, "读取规则": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old_rules["扫描目录"] = sorted(manifests)
    old_rules["编号定义"] = destination(old_rules["编号定义"])
    for key in ("地点主体", "地点专属内容"):
        old_rules["归属规则"][key] = old_rules["归属规则"][key].replace("内容/世界/", "世界/内容/")
    (DATA / "基础/读取规则.json").write_text(json.dumps(old_rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for kind in KINDS:
        for directory in sorted((DATA / kind).rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if directory.is_dir():
                directory.rmdir()
        (DATA / kind).rmdir()
    # Update literal path references in documentation and diagnostic strings.
    replacements = dict(mapping)
    for kind in KINDS:
        for old in mapping:
            parts = old.split("/")
            if len(parts) > 2 and parts[0] == kind and parts[1] != "玩法":
                prefix = "/".join(parts[:2]) + "/"
                replacements[prefix] = destination(prefix + "PLACEHOLDER").removesuffix("PLACEHOLDER")
    candidates = [p for folder in (DATA, ROOT / "game", ROOT / "launch") for p in folder.rglob("*") if p.suffix in (".md", ".py")]
    candidates += list(ROOT.glob("*.md"))
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        pattern = re.compile("|".join(re.escape(k) for k in sorted(replacements, key=len, reverse=True)))
        updated = pattern.sub(lambda m: replacements[m.group()], text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
    (ROOT / "tools/组件迁移清单.json").write_text(json.dumps({"文件映射": mapping, "原始JSON哈希": hashes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Moved {len(mapping)} files; verified {len(hashes)} JSON payloads; {len(manifests)} components")


if __name__ == "__main__":
    main()
