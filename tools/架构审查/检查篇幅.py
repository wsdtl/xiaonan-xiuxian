"""篇幅棘轮：文件与函数不能越写越长。

委托方 2026-10：「我要**诗歌一样的代码**」。篇幅是最可查的那一条：现在 4684 个函数**中位数 11 行**、平均 18 行，
健康；但尾巴很长——最长的文件 3906 行、最长的函数 749 行。**一次拆完不现实，所以用棘轮**：

- 文件 ≤ **800 行**、函数 ≤ **120 行**；
- 现在超标的 27 个文件与 29 个函数进白名单（连同当时的行数）；
- **白名单只减不增**：已列的不许变长，没列的不许超标。**拆小一个就从白名单删一条。**

**为什么用名字而不是行号定位函数**：行号会被上面的改动推走，名字（`类.方法`）稳。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查篇幅.py

**退出码：0 = 干净，1 = 有违规。**
"""
from __future__ import annotations

import ast
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_PARTS = {".venv", ".git", "__pycache__", "_输出"}

#: 文件行数上限与函数行数上限。
FILE_CAP = 800
FUNC_CAP = 120

#: 已超标者（只减不增）。删掉一条 = 把那个文件或函数拆到上限内。
_WHITELIST = json.loads(
    """{"files":{"game/app.py":1022,"game/core/alchemy/service.py":887,"game/core/asset/service.py":1379,"game/core/character/service.py":2307,"game/core/combat/card_text.py":2062,"game/core/combat/engine.py":2222,"game/core/combat/mechanics.py":3906,"game/core/combat/models.py":1228,"game/core/combat/presentation.py":936,"game/core/companion/service.py":1848,"game/core/database/storage.py":1591,"game/core/exploration/service.py":1487,"game/core/forging/service.py":938,"game/core/formation/service.py":1092,"game/core/gathering/service.py":860,"game/core/hosting/service.py":925,"game/core/player_state/service.py":860,"game/core/retreat/service.py":921,"game/core/sect/service.py":1021,"game/core/sect_assets/service.py":948,"game/core/sect_war/service.py":1168,"game/core/world/service.py":1014,"tools/库/构筑模板.py":801,"tools/架构审查/检查数据驱动.py":954,"tools/架构审查/检查消息零信息.py":1123,"tools/架构审查/检查边界.py":1274,"tools/行为验证/验证规则层.py":1036},"funcs":{"game/app.py::build_game_services":749,"game/cmd/通用/角色/reply.py::overview":165,"game/core/combat/engine.py::BattleEngine.__init__":133,"game/core/combat/engine.py::BattleEngine._apply_damage":267,"game/core/combat/engine.py::BattleEngine.simulate_teams":125,"game/core/combat/mechanics.py::AbilityRuntime._ability_add_status":145,"game/core/combat/mechanics.py::AbilityRuntime._dispatch_event_body":313,"game/core/combat/mechanics.py::AbilityRuntime._listeners_for":127,"game/core/combat/presentation.py::build_battle_report_view":326,"game/core/combat/rules.py::validate_rule_layer":132,"game/core/companion/service.py::CompanionService._definition":128,"game/core/enemy/service.py::EnemyService._instance":159,"game/core/exploration/service.py::ExplorationService.settle":136,"game/core/exploration/service.py::ExplorationService.start":499,"game/core/gathering/service.py::GatheringService.start":167,"game/core/raid/service.py::RaidService.start":140,"game/core/retreat/service.py::RetreatService.settle":180,"game/core/retreat/service.py::RetreatService.start":168,"game/core/sect_production/service.py::SectProductionService.collect":138,"game/core/sect_war/service.py::SectWarService.start":190,"game/core/world/service.py::WorldService.initialize":137,"game/features/daolv_jiejiao/service.py::CompanionInteractionFeature.gift":180,"game/features/fudan/service.py::MedicineFeature.use":126,"game/features/weizhi/presentation.py::_position_copy":221,"tools/行为验证/验证QQWebSocket.py::run":146}}"""
)
WHITELIST_FILES: dict[str, int] = _WHITELIST["files"]
WHITELIST_FUNCS: dict[str, int] = _WHITELIST["funcs"]


def _functions(rel: str, text: str) -> dict[str, int]:
    """本文件里每个函数的行数，键是「类.方法」或函数名。"""

    out: dict[str, int] = {}

    class Visit(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if node.end_lineno:
                out[rel + "::" + ".".join([*self.stack, node.name])] = (
                    node.end_lineno - node.lineno + 1
                )
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _record
        visit_AsyncFunctionDef = _record

    Visit().visit(ast.parse(text))
    return out


def main() -> int:
    problems: list[str] = []
    files: dict[str, int] = {}
    funcs: dict[str, int] = {}
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        size = text.count("\n") + 1
        if size > FILE_CAP:
            files[rel] = size
        try:
            funcs.update(_functions(rel, text))
        except SyntaxError:
            continue
    for rel, size in sorted(files.items()):
        known = WHITELIST_FILES.get(rel)
        if known is None:
            problems.append(f"{rel} 有 {size} 行，超过 {FILE_CAP} 行上限（新超标）")
        elif size > known:
            problems.append(f"{rel} 从白名单的 {known} 行涨到 {size} 行（棘轮只减不增）")
    for key, size in sorted(funcs.items()):
        if size <= FUNC_CAP:
            continue
        known = WHITELIST_FUNCS.get(key)
        if known is None:
            problems.append(f"{key} 有 {size} 行，超过 {FUNC_CAP} 行上限（新超标）")
        elif size > known:
            problems.append(f"{key} 从白名单的 {known} 行涨到 {size} 行（棘轮只减不增）")
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"篇幅棘轮 {len(problems)} 处有问题")
        return 1
    print(
        f"篇幅棘轮 干净（文件上限 {FILE_CAP} 行、函数上限 {FUNC_CAP} 行；"
        f"白名单里还剩 {len(WHITELIST_FILES)} 个文件、{len(WHITELIST_FUNCS)} 个函数待拆）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
