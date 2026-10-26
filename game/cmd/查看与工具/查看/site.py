"""百科页面：按编号前缀浏览全部已 ID 化的实体。

融合在「查看」组件里——不另立二级组件。页面走 `/baike`，数据走 `/baike/data`。

**事实全部来自玩法**（`features.chakan_wupin`）：总表、前缀计数、单条详情与引用图都由它给；
页面只做筛选、汇总与 JSON 编码，不碰任何核心服务。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse

from game.app import current_game_services
from launch.paths import static_path

from ...site import PAGE_HEADERS

#: 百科页要把图片画在 <canvas> 或内联 data: 图片上，所以在本页单独声明内容安全策略。
PAGE_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def _page_headers() -> dict[str, str]:
    """这一页的响应头：共用基础头 + 本页策略与来源限制。

    头名显式写在本页——下发 HTML 的模块自己声明内容安全策略。
    """

    return {
        **PAGE_HEADERS,
        "Content-Security-Policy": PAGE_CSP,
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "SAMEORIGIN",
    }

router = APIRouter(prefix="/baike")
INDEX_HTML: Path = static_path("tool", "baike", "index.html")


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def baike_page() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"), headers=_page_headers())




@router.get("/data", response_class=JSONResponse)
async def baike_data(prefix: str = "", q: str = "", id: str = "") -> JSONResponse:
    """`id` 给单个实体的详情；`q` 按编号或名称检索；`prefix` 给该前缀的条目；都不带给前缀总表。"""

    feature = current_game_services().features.chakan_wupin
    wanted_id = id.strip()
    if wanted_id:
        return _detail(feature, wanted_id)
    catalog = feature.catalog()
    entries = [
        {"编号": row.entity_id, "名称": row.name, "来源": row.source}
        for row in catalog.entries
    ]
    query = q.strip()
    if query:
        picked = [e for e in entries if query in e["编号"] or query == e["名称"]]
        return JSONResponse({"模式": "检索", "查询": query, "条目": picked[:500]}, headers=PAGE_HEADERS)
    wanted = prefix.strip()
    if wanted:
        picked = [e for e in entries if e["编号"].startswith(wanted)]
        return JSONResponse({"模式": "前缀", "前缀": wanted, "条目": picked}, headers=PAGE_HEADERS)
    table = [
        {"前缀": row.prefix, "主体": row.subject, "类别": row.category, "条数": row.count}
        for row in catalog.prefix_rows
    ]
    return JSONResponse(
        {
            "模式": "总表",
            "前缀表": table,
            "总数": len(entries),
            "前缀数": len(table),
            "主体表": _group_rows(table),
        },
        headers=PAGE_HEADERS,
    )


def _detail(feature, entity_id: str) -> JSONResponse:
    """单条详情：事实来自玩法，页面只编码成 JSON。"""

    got = feature.detail(entity_id)
    if got is None:
        missing = "没有这个种族" if feature.is_race(entity_id) else "没有这个编号"
        return JSONResponse(
            {"模式": "详情", "编号": entity_id, "错误": missing},
            status_code=404,
            headers=PAGE_HEADERS,
        )
    body: dict[str, object] = {
        "模式": "详情",
        "编号": got.entity_id,
        "名称": got.name,
        "来源": got.source,
    }
    if got.number_category:
        body["编号类别"] = got.number_category
    body["字段"] = jsonable_encoder(got.fields)
    body["引用"] = [
        {"字段": ref.field, "编号": ref.entity_id, "名称": ref.name}
        for ref in got.references
    ]
    return JSONResponse(body, headers=PAGE_HEADERS)


def _group_rows(table: list[dict[str, object]]) -> list[dict[str, object]]:
    """按登记表的 `主体` 汇总条数与前缀数——**汇总只能由后台给**（static/说明.md 的硬规矩）。"""

    order: list[str] = []
    counted: dict[str, list[int]] = {}
    for row in table:
        group = str(row.get("主体") or "")
        if group not in counted:
            counted[group] = [0, 0]
            order.append(group)
        counted[group][0] += int(row.get("条数") or 0)
        counted[group][1] += 1
    return [
        {"主体": group, "条数": counted[group][0], "前缀数": counted[group][1]}
        for group in order
    ]


__all__ = ["router"]
