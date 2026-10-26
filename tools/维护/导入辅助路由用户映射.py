"""把人工核对的 openid -> QQ 号别名导入辅助路由库。

只写 database/assist_router.db，不读写 game.db。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assist_router.config import AssistRouterSettings
from assist_router.store import AssistRouterStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mapping",
        nargs="?",
        default="_输出/辅助路由用户映射.json",
        help="JSON 映射文件路径",
    )
    args = parser.parse_args()

    path = Path(args.mapping)
    items = json.loads(path.read_text(encoding="utf-8"))
    settings = AssistRouterSettings()
    store = AssistRouterStore(settings.db_path)
    store.open()
    try:
        for item in items:
            openid = str(item.get("openid") or "").strip()
            qq_uin = str(item.get("qq_uin") or "").strip()
            scene = str(item.get("scene") or "").strip()
            group_openid = str(item.get("group_openid") or "").strip()
            if not openid or not qq_uin or not scene:
                raise ValueError(f"映射缺少 openid/qq_uin/scene：{item}")
            store.upsert_user_alias(
                official_bot_key=str(item.get("bot_key") or "102134058"),
                openid=openid,
                qq_uin=qq_uin,
                scene=scene,
                group_openid=group_openid,
                confidence=int(item.get("confidence") or 100),
                status="confirmed",
                evidence={"source": "manual-import", "name": item.get("name", "")},
            )
        print(f"已导入 {len(items)} 条用户别名 -> {settings.db_path}")
        print(store.stats())
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
