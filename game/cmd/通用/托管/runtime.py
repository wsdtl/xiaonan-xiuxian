"""用本地驱动器按托管计划触发正式游戏命令。"""

from __future__ import annotations

from collections.abc import Sequence
from launch.adapter.local import LocalReply

from game.features.tuoguan import HostingSession

import asyncio
from datetime import datetime, timedelta, timezone

from game.app import current_game_services
from launch import OnEvent, Scheduler
from launch.adapter import dispatch_local_message

JOB_PREFIX = "hosting-plan-"


@OnEvent.connect(priority=200)
async def restore_hosting_jobs() -> None:
    """热重启后只恢复当前步骤，不追赶停机期间错过的循环。"""

    for session in await current_game_services().features.tuoguan.active_plans():
        schedule_plan(session)


def schedule_plan(session: HostingSession) -> None:
    if (
        session.status != "运行中"
        or session.next_trigger_at is None
        or not Scheduler.instance.running
    ):
        return
    current = datetime.now(timezone.utc)
    run_date = max(session.next_trigger_at, current + timedelta(milliseconds=50))
    Scheduler.instance.add_job(
        run_hosting_plan,
        "date",
        run_date=run_date,
        args=(session.session_id,),
        id=f"{JOB_PREFIX}{session.session_id}",
        replace_existing=True,
        misfire_grace_time=86400,
    )


def cancel_plan(session_id: str) -> None:
    job_id = f"{JOB_PREFIX}{str(session_id or '').strip()}"
    if not Scheduler.instance.running:
        return
    job = Scheduler.instance.get_job(job_id)
    if job is not None:
        job.remove()


async def run_hosting_plan(session_id: str) -> None:
    """结束一步后可立即开始下一步，每次唤醒最多分发两条命令。"""
    try:
        hosting = current_game_services().features.tuoguan
        current_session = None
        for _ in range(2):
            execution = await hosting.claim_execution(session_id)
            if execution is None:
                return
            result = await dispatch_local_message(
                user_id=execution.leader_user_id,
                raw_message=execution.command,
                event_id=execution.request_id,
            )
            success = result.matched and await hosting.verify_execution(execution)
            error = ""
            if not result.matched:
                error = f"托管无法执行“{execution.command}”，该命令当前不可用。"
            elif not success:
                error = _reply_error(result.replies) or (
                    f"“{execution.command}”没有完成，请查看人物当前状态。"
                )
            current_session = await hosting.complete_execution(
                execution,
                success=success,
                error=error,
            )
            if current_session is None or current_session.status != "运行中":
                return
            if execution.phase == "执行开始":
                schedule_plan(current_session)
                return
        if current_session is not None:
            schedule_plan(current_session)
    except asyncio.CancelledError:
        # 热重启会取消正在唤醒的作业；计划仍在数据库中，启动后会重新恢复。
        return


def _reply_error(replies: Sequence[LocalReply]) -> str:
    if not replies:
        return ""
    message = replies[-1].message
    content = getattr(message, "content", message)
    parts: list[str] = []
    for raw_line in str(content or "").replace("&nbsp;", " ").splitlines():
        line = raw_line.strip()
        while line.startswith(">"):
            line = line[1:].strip()
        line = line.strip("*").strip()
        if line:
            parts.append(line)
    return " ".join(parts)[:240]


__all__ = ["cancel_plan", "run_hosting_plan", "schedule_plan"]
