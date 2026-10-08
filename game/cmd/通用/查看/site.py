"""百科页面：按编号前缀浏览全部已 ID 化的实体。

融合在「查看」组件里——不另立二级组件。页面走 `/baike`，数据走 `/baike/data`。
数据只有两个来源，都是既有核心的公共读口，不新建数据：

1. `JsonDataService.numbered_entities()`：21 个前缀（3628 条，实测）；
2. 角色核心的 `races()`：前缀 `55`（180 个）。两者合计覆盖登记表里全部 22 个前缀。
"""

from __future__ import annotations

import json
from pathlib import Path

from collections.abc import Mapping

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

router = APIRouter(prefix="/baike")
INDEX_HTML: Path = static_path("baike", "index.html")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def baike_page() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"), headers=_page_headers())


@router.get("/data", response_class=JSONResponse)
async def baike_data(prefix: str = "", q: str = "", id: str = "") -> JSONResponse:
    """`id` 给单个实体的详情；`q` 按编号或名称检索；`prefix` 给该前缀的条目；都不带给前缀总表。"""

    services = current_game_services()
    wanted_id = id.strip()
    if wanted_id:
        return _detail(services, wanted_id)
    entries = _entries(services)
    query = q.strip()
    if query:
        picked = [e for e in entries if query in e["编号"] or query == e["名称"]]
        return JSONResponse({"模式": "检索", "查询": query, "条目": picked[:500]}, headers=_data_headers())
    wanted = prefix.strip()
    if wanted:
        picked = [e for e in entries if e["编号"].startswith(wanted)]
        return JSONResponse({"模式": "前缀", "前缀": wanted, "条目": picked}, headers=_data_headers())
    return JSONResponse({"模式": "总表", "前缀表": _prefix_rows(entries)}, headers=_data_headers())


def _detail(services, entity_id: str) -> JSONResponse:
    """单个实体的详情。按前缀分派：数据索引实体走 `entity_record`，种族走角色核心的 `races()`。"""

    headers = _data_headers()
    if entity_id.startswith("55"):
        race = services.core.character.races().get(entity_id) or _find_race(services, entity_id)
        if race is None:
            return JSONResponse(
                {"模式": "详情", "编号": entity_id, "错误": "没有这个种族"},
                status_code=404,
                headers=headers,
            )
        return JSONResponse(
            {
                "模式": "详情",
                "编号": entity_id,
                "名称": str(race.get("种族") or ""),
                "来源": "种族",
                "字段": jsonable_encoder(race),
            },
            headers=headers,
        )
    record = None
    for entity in services.core.data.numbered_entities():
        if entity.entity_id == entity_id:
            record = entity
            break
    if record is None:
        return JSONResponse(
            {"模式": "详情", "编号": entity_id, "错误": "没有这个编号"},
            status_code=404,
            headers=headers,
        )
    return JSONResponse(
        {
            "模式": "详情",
            "编号": entity_id,
            "名称": str(record.value.get("名称") or entity_id),
            "来源": str(record.section),
            "编号类别": str(record.number_category),
            "字段": jsonable_encoder(record.value),
        },
        headers=headers,
    )


def _find_race(services, entity_id: str) -> Mapping | None:
    """种族登记表按名字索引，详情按编号取，所以要按编号再找一遍。"""

    for race in services.core.character.races().values():
        if str(race.get("编号") or "") == entity_id:
            return race
    return None


def _entries(services) -> list[dict[str, str]]:
    """全部带编号的条目：数据索引 + 角色核心的种族，按编号排序。"""

    numbered = services.core.data.numbered_entities()
    rows = [
        {
            "编号": str(entity.entity_id),
            "名称": str(entity.value.get("名称") or entity.entity_id),
            "来源": str(entity.section),
        }
        for entity in numbered
    ]
    rows += [
        {
            "编号": str(race.get("编号") or ""),
            "名称": str(race.get("种族") or ""),
            "来源": "种族",
        }
        for race in services.core.character.races().values()
    ]
    return sorted((row for row in rows if row["编号"]), key=lambda row: row["编号"])


def _registry(services) -> list[dict]:
    """编号登记表。`基础/定义/编号.json` 并进数据集 `基础定义`，按已知键直接索引读。

    边界审查禁止业务代码自行 walk 数据结构（正式 JSON 只由 `game/core/data` 建索引），
    所以这里只走登记表自己那一层键，不做遍历。
    """

    document = services.core.data.dataset("基础定义").get("编号") or {}
    rows = document.get("编号前缀") or () if isinstance(document, Mapping) else ()
    return [row for row in rows if isinstance(row, Mapping)]

def _prefix_rows(entries: list[dict[str, str]]) -> list[dict[str, object]]:
    """登记表里的 22 个前缀，各自数一数有多少条。"""

    registry = _registry(current_game_services())
    counted: dict[str, int] = {}
    for entry in entries:
        key = entry["编号"][:2]
        counted[key] = counted.get(key, 0) + 1
    return [
        {
            "前缀": str(row.get("前缀") or ""),
            "主体": str(row.get("主体") or ""),
            "类别": str(row.get("类别") or ""),
            "条数": counted.get(str(row.get("前缀") or ""), 0),
        }
        for row in registry
    ]


def _page_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
    }


def _data_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


__all__ = ["router"]
