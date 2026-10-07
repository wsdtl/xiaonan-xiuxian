"""装配台契约：装配码、命令层、网页接口与真实临时库集成。

由原 test_zhuangpei.py + test_zhuangpei_codec.py + test_zhuangpei_site.py 并档而来：它们本就同属一个领域，
分开写只会让每份都重新装一遍服务。
"""
from __future__ import annotations

import asyncio
import importlib
import itertools
import json
import socket
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
import uvicorn

from game.core.asset import CultivationAcquisition
from game.core.database import StateAddress, StateMutation, TransactionCommand, StateConflictError
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.zhuangpei import ZhuangpeiFeatureError, encode, decode

counter = itertools.count(1)


class HttpClient:
    """通过真实本地 HTTP 测试路由，复用运行时依赖，不另加测试客户端库。"""
    def __init__(self, app):
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.base = f"http://127.0.0.1:{self.socket.getsockname()[1]}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("测试 HTTP 服务启动超时")
            time.sleep(.01)
        return self

    def __exit__(self, *args):
        self.server.should_exit = True
        self.thread.join(5)
        self.socket.close()

    def get(self, path):
        return self.request(path)

    def post(self, path, *, json=None, content=None):
        data = content if content is not None else globals()["json"].dumps(json).encode()
        return self.request(path, data)

    def request(self, path, data=None):
        try:
            response = urlopen(Request(self.base + path, data=data, headers={"Content-Type": "application/json"}), timeout=10)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            return SimpleNamespace(status_code=response.status, headers=response.headers, json=lambda: json.loads(body))


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    import game.app as app
    original = app.game_config
    app.game_config = replace(original, database=replace(original.database, path=tmp_path_factory.mktemp("assembly") / "game.db"))
    try:
        value = app.build_game_services()
    finally:
        app.game_config = original
    yield value
    value.core.database.close()


def blank():
    return {"功法": [], "真意": [], "气机": [], "器律": []}


def item(content_id, grade="01"):
    return {"编号": content_id, "品级": grade}


async def player(s):
    number = next(counter)
    uid = f"assembly-{number}"
    await s.features.chuangjian_renwu.create(CreateCharacterRequest(uid, f"create-{number}", f"装配{number}", "男"))
    return uid


async def commit(s, uid, operations):
    await s.core.database.commit(TransactionCommand(uid, f"seed-{next(counter)}", "测试置备", tuple(operations), {}))


async def acquire(s, uid, section, content_id, quantity=1):
    if section == "功法":
        plan = await s.core.asset.plan_cultivation_acquisitions(uid, (CultivationAcquisition(section, content_id, "01"),))
        await commit(s, uid, plan.operations)
    elif section == "器律":
        plan = await s.core.asset.plan_law_reserve_acquisition(uid, content_id, quantity)
        await commit(s, uid, (plan.operation,))
    else:
        plan = await s.core.asset.plan_cultivation_reserve_change(uid, category=section, content_id=content_id, grade_id="01", quantity_delta=quantity)
        await commit(s, uid, (plan.operation,))


async def snapshot(s, uid):
    return await s.core.database.list_for_user(uid)


async def change(s, uid, kind, values):
    old = await s.core.database.get(StateAddress(uid, kind, "main"))
    await commit(s, uid, (StateMutation(uid, kind, "main", {**old.value, **values}, old.version),))


def test_full_pool_is_independent_and_scopes_are_flat(services):
    async def run():
        f = services.features.zhuangpei
        assert await f.scopes() == [{"id": "all", "name": "全池"}]
        full = await f.page()
        assert len(full["entries"]) > 1000
        assert {e["section"] for e in full["entries"]} == set(blank())
        a, b = await player(services), await player(services)
        await acquire(services, a, "功法", "400001")
        await acquire(services, b, "功法", "400002")
        with pytest.raises(ZhuangpeiFeatureError):
            await f.page("user:" + a)
        assert await f.toggle_public(a, "publish-a")
        assert await f.toggle_public(a, "publish-a")
        assert await f.toggle_public(b, "publish-b")
        assert [x["id"] for x in await f.scopes()] == ["all", "user:" + a, "user:" + b]
        assert {e["id"] for e in (await f.page("user:" + a))["entries"]} == {"400001"}
        assert len((await f.page())["entries"]) == len(full["entries"])
        assert not await f.toggle_public(a, "close-a")
        assert await f.toggle_public(a, "publish-a")  # 老回执不能重新开启
        with pytest.raises(ZhuangpeiFeatureError):
            await f.page("user:" + a)
        assert not await f.toggle_public(b, "close-b")
    asyncio.run(run())


def test_real_batch_import_replay_and_current(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        build = blank()
        for section, cid in (("功法", "400001"), ("真意", "410001"), ("气机", "420001")):
            await acquire(s, uid, section, cid)
            build[section] = [item(cid)]
        code = encode(build)
        result = await f.import_code(uid, "import", code)
        assert not result.replayed and result.code == code
        before = await snapshot(s, uid)
        assert (await f.import_code(uid, "import", code)).replayed
        assert await snapshot(s, uid) == before
        assert (await f.current(uid)).code == code
        assert await s.core.asset.cultivation_reserve_stack(uid, "真意", "410001", "01") is None
        # 相同内容仍在原槽，不需要第二份库存。
        await f.import_code(uid, "same-build-new-request", code)
        assert (await f.current(uid)).code == code
        await f.toggle_public(uid, "public")
        rows = (await f.page("user:" + uid))["entries"]
        assert next(e for e in rows if e["id"] == "410001")["equipped"] == [1]
        with pytest.raises(ZhuangpeiFeatureError, match="同一请求"):
            await f.import_code(uid, "import", encode(blank()))
    asyncio.run(run())


def test_missing_stock_rolls_back_everything(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        await acquire(s, uid, "功法", "400001")
        await acquire(s, uid, "真意", "410001")
        build = {**blank(), "功法": [item("400001")], "真意": [item("410001")], "气机": [item("420001")]}
        before = await snapshot(s, uid)
        with pytest.raises(ZhuangpeiFeatureError):
            await f.import_code(uid, "not-enough", encode(build))
        assert await snapshot(s, uid) == before
        assert await s.core.database.committed_transaction(uid, "not-enough") is None
    asyncio.run(run())


@pytest.mark.parametrize("build", [
    {**blank(), "功法": [item("400001"), item("400001")]},
    {**blank(), "功法": [None]*6 + [item("400001")]},
    {**blank(), "功法": [item("999999")]},
    {**blank(), "功法": [item("400001", "99")]},
    {**blank(), "功法": [item("420001")]},
])
def test_invalid_scheme_rejected(services, build):
    with pytest.raises(ZhuangpeiFeatureError):
        services.features.zhuangpei.scheme(build)


def test_law_quantity_and_weapon_slot_rules(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        law = next(iter(s.core.data.entities("器律")))
        build = {**blank(), "器律": [item(law, ""), item(law, "")]}
        await acquire(s, uid, "器律", law, 1)
        before = await snapshot(s, uid)
        with pytest.raises(ZhuangpeiFeatureError):
            await f.import_code(uid, "low-level", encode(build))
        assert await snapshot(s, uid) == before
        level = s.core.forging.status().weapon_maximum_level
        await change(s, uid, "weapon", {"等级": level, "器阶": s.core.forging.weapon_stage(level).name})
        before = await snapshot(s, uid)
        with pytest.raises(ZhuangpeiFeatureError, match="不足"):
            await f.import_code(uid, "short-law", encode(build))
        assert await snapshot(s, uid) == before
        await acquire(s, uid, "器律", law)
        await f.import_code(uid, "laws", encode(build))
        assert (await f.current(uid)).code == encode(build)
        assert await s.core.database.get(StateAddress(uid, "law_reserve", law)) is None
        await f.import_code(uid, "keep-laws", encode(build))
    asyncio.run(run())


def test_two_requests_same_inventory_only_one_consumes(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        await acquire(s, uid, "真意", "410001")
        code = encode({**blank(), "真意": [item("410001")]})
        results = await asyncio.gather(f.import_code(uid, "same", code), f.import_code(uid, "same", code))
        assert all(r.code == code for r in results)
        assert await s.core.asset.cultivation_reserve_stack(uid, "真意", "410001", "01") is None
    asyncio.run(run())


def test_stale_plan_cannot_partially_commit(services):
    async def run():
        s = services
        uid = await player(s)
        await acquire(s, uid, "真意", "410001", 2)
        build = {**blank(), "真意": [item("410001")]}
        plan = await s.core.character.plan_assembly(uid, build)
        await change(s, uid, "weapon", {"名称": "变更过的武器"})
        before = await snapshot(s, uid)
        with pytest.raises(StateConflictError):
            await commit(s, uid, plan.operations)
        assert await snapshot(s, uid) == before
    asyncio.run(run())


def test_http_contract_and_read_only_scheme(services, monkeypatch):
    site = importlib.import_module("game.cmd.通用.装配台.site")
    monkeypatch.setattr(site, "current_game_services", lambda: services)
    app = FastAPI()
    app.include_router(site.router)
    with HttpClient(app) as client:
        page = client.get("/assembly")
        assert page.status_code == 200 and "Content-Security-Policy" in page.headers
        assert page.headers["cache-control"] == "no-store"
        assert client.get("/assembly/data").json()["scope"] == "all"
        assert client.get("/assembly/data?scope=user:private").status_code == 400
        count = services.core.database.status().transaction_count
        value = client.post("/assembly/scheme", json={"build": blank()})
        assert value.status_code == 200
        assert client.post("/assembly/scheme", json={"code": value.json()["code"]}).json() == value.json()
        for payload in ({"code": "bad"}, [], {"build": {}}, {"build": {**blank(), "功法": [item("400001", "99")]}}, {"user": "x", "build": blank()}):
            assert client.post("/assembly/scheme", json=payload).status_code == 400
        assert client.post("/assembly/scheme", content=b"bad").status_code == 400
        assert client.post("/assembly/scheme", content=b"x"*32769).status_code == 413
        assert client.get("/assembly/arbitrary-user/data").status_code == 404
        assert services.core.database.status().transaction_count == count


def test_command_reaches_write_and_document_reply(services, monkeypatch):
    module = importlib.import_module("game.cmd.通用.装配台")
    monkeypatch.setattr(module, "current_game_services", lambda: services)
    sent = []
    async def send(value): sent.append(value)
    async def run():
        uid = await player(services)
        await acquire(services, uid, "功法", "400001")
        code = encode({**blank(), "功法": [item("400001")]})
        await module.import_assembly(user_id=uid, message=code, message_context=SimpleNamespace(request_id="chat-import"), manager=SimpleNamespace(send=send))
        assert (await services.features.zhuangpei.current(uid)).code == code
        assert sent[-1].__class__.__name__ == "DocumentMessage"
        await module.assembly(manager=SimpleNamespace(send=send))
        assert "/assembly" in str(sent[-1])
        await module.my_assembly(user_id=uid, manager=SimpleNamespace(send=send))
        assert code in str(sent[-1])
    asyncio.run(run())


@pytest.mark.parametrize("retain", [False, True])
def test_replacement_retains_only_with_existing_treasure(services, retain):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        if retain:
            p = await s.core.innate_treasure.plan_acquire(uid, "540008")
            await commit(s, uid, (p.operation,))
            p = await s.core.innate_treasure.plan_equip(uid, "540008")
            await commit(s, uid, (p.operation,))
        for cid in ("410001", "410002"):
            await acquire(s, uid, "真意", cid)
        await f.import_code(uid, "first", encode({**blank(), "真意": [item("410001")]}))
        await f.import_code(uid, "replace", encode({**blank(), "真意": [item("410002")]}))
        old = await s.core.asset.cultivation_reserve_stack(uid, "真意", "410001", "01")
        assert (old.quantity if old else 0) == int(retain)
        assert await s.core.asset.cultivation_reserve_stack(uid, "真意", "410002", "01") is None
        await f.import_code(uid, "clear", encode(blank()))
        assert await s.core.asset.cultivation_reserve_stack(uid, "真意", "410002", "01") is None
        assert (await f.current(uid)).code == encode(blank())
    asyncio.run(run())


def test_final_conflict_checked_without_transient_conflict(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        for cid in ("400016", "400085"):
            await acquire(s, uid, "功法", cid)
        await f.import_code(uid, "first", encode({**blank(), "功法": [None, item("400016")]}))
        # 若按槽位 1 再槽位 2 顺序装，会临时与旧槽相冲；整套最终状态合法。
        target = {**blank(), "功法": [item("400085")]}
        await f.import_code(uid, "whole", encode(target))
        assert (await f.current(uid)).code == encode(target)
        before = await snapshot(s, uid)
        with pytest.raises(ZhuangpeiFeatureError, match="相冲"):
            await f.import_code(uid, "bad", encode({**blank(), "功法": [item("400085"), item("400016")]}))
        assert await snapshot(s, uid) == before
    asyncio.run(run())


def test_borrowed_slot_metadata_and_cross_user_code_validation(services):
    async def run():
        from game.core.world import LocationQuery
        s, f = services, services.features.zhuangpei
        leader, borrower, other = await player(s), await player(s), await player(s)
        await acquire(s, leader, "功法", "400001")
        xy = s.core.world.locate(LocationQuery(location_name=s.features.chuangjian_renwu._birthplace)).xy
        await s.core.sect.create(leader, "sect", "装配借阅宗", xy)
        await s.core.sect.invite(leader, borrower, "invite")
        await s.core.sect.accept(borrower, "join")
        await s.core.sect_library.borrow(borrower, "borrow", "400001", 1)
        state = await s.core.database.get(StateAddress(borrower, "cultivation", "main"))
        old = state.value["功法"][0]
        assert "藏经阁借阅" in old
        code = (await f.current(borrower)).code
        await f.import_code(borrower, "unchanged", code)
        state = await s.core.database.get(StateAddress(borrower, "cultivation", "main"))
        assert state.value["功法"][0] == old
        before = await snapshot(s, other)
        with pytest.raises(ZhuangpeiFeatureError):
            await f.import_code(other, "other", code)
        assert await snapshot(s, other) == before
        await acquire(s, other, "功法", "400001")
        await f.import_code(other, "other", code)
        assert (await f.current(other)).code == code
        await s.features.zongmen.leave(borrower, "leave")
        assert (await f.current(borrower)).code == encode(blank())
    asyncio.run(run())


def test_grade_mismatch_and_uncreated_user(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        await acquire(s, uid, "功法", "400001")
        before = await snapshot(s, uid)
        with pytest.raises(ZhuangpeiFeatureError, match="品"):
            await f.import_code(uid, "grade", encode({**blank(), "功法": [item("400001", "02")]}))
        assert await snapshot(s, uid) == before
        with pytest.raises(ZhuangpeiFeatureError, match="创建"):
            await f.import_code("unknown-player", "missing", encode(blank()))
    asyncio.run(run())


def test_busy_guard_prevents_import(services):
    async def run():
        s = services
        uid = await player(s)
        await change(s, uid, "player_state", {"行为": {"状态编号": "520004", "上下文": {}}})
        before = await snapshot(s, uid)
        with pytest.raises(ZhuangpeiFeatureError, match="闭关"):
            await s.features.zhuangpei.import_code(uid, "busy", encode(blank()))
        assert await snapshot(s, uid) == before
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["player_state", "innate_treasure", "cultivation_library"])
def test_concurrent_guard_or_ownership_change_aborts_import(services, monkeypatch, kind):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        await acquire(s, uid, "功法", "400001")
        code = encode({**blank(), "功法": [item("400001")]})
        original = s.core.character.plan_assembly
        after_race = None
        async def race(*args, **kwargs):
            nonlocal after_race
            plan = await original(*args, **kwargs)
            if kind == "player_state":
                await change(s, uid, kind, {"行为": {"状态编号": "520004", "上下文": {}}})
            elif kind == "innate_treasure":
                p = await s.core.innate_treasure.plan_acquire(uid, "540008")
                await commit(s, uid, (p.operation,))
            else:
                old = await s.core.database.get(StateAddress(uid, kind, "400001"))
                await commit(s, uid, (StateMutation(uid, kind, "400001", {"编号": "400001", "品级": "02"}, old.version),))
            after_race = await snapshot(s, uid)
            return plan
        monkeypatch.setattr(s.core.character, "plan_assembly", race)
        with pytest.raises(ZhuangpeiFeatureError, match="变化"):
            await f.import_code(uid, "race", code)
        assert await snapshot(s, uid) == after_race
        assert await s.core.database.committed_transaction(uid, "race") is None
    asyncio.run(run())


def test_concurrent_public_toggle_same_request(services):
    async def run():
        uid = await player(services)
        f = services.features.zhuangpei
        assert await asyncio.gather(f.toggle_public(uid, "same"), f.toggle_public(uid, "same")) == [True, True]
        assert "user:" + uid in {s["id"] for s in await f.scopes()}
        assert not await f.toggle_public(uid, "close")
        assert "user:" + uid not in {s["id"] for s in await f.scopes()}
        with pytest.raises(ZhuangpeiFeatureError):
            await f.import_code(uid, "same", encode(blank()))
    asyncio.run(run())


def test_privacy_rechecked_during_read(services, monkeypatch):
    async def run():
        uid = await player(services)
        f = services.features.zhuangpei
        await f.toggle_public(uid, "on")
        original = services.core.asset.snapshot
        async def close_while_reading(user_id):
            await f.toggle_public(uid, "off")
            return await original(user_id)
        monkeypatch.setattr(services.core.asset, "snapshot", close_while_reading)
        with pytest.raises(ZhuangpeiFeatureError, match="关闭"):
            await f.page("user:" + uid)
    asyncio.run(run())


def test_swap_refunds_aggregate_without_double_inventory_operations(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        p = await s.core.innate_treasure.plan_acquire(uid, "540008")
        await commit(s, uid, (p.operation,))
        p = await s.core.innate_treasure.plan_equip(uid, "540008")
        await commit(s, uid, (p.operation,))
        for cid in ("410001", "410002"):
            await acquire(s, uid, "真意", cid, 2)
        first = {**blank(), "真意": [item("410001"), item("410002")]}
        await f.import_code(uid, "first", encode(first))
        second = {**blank(), "真意": list(reversed(first["真意"]))}
        await f.import_code(uid, "swap", encode(second))
        for cid in ("410001", "410002"):
            assert (await s.core.asset.cultivation_reserve_stack(uid, "真意", cid, "01")).quantity == 1
        assert (await f.current(uid)).code == encode(second)
    asyncio.run(run())


def test_refund_cannot_finance_new_slots(services):
    async def run():
        s, f = services, services.features.zhuangpei
        uid = await player(s)
        p = await s.core.innate_treasure.plan_acquire(uid, "540008")
        await commit(s, uid, (p.operation,))
        p = await s.core.innate_treasure.plan_equip(uid, "540008")
        await commit(s, uid, (p.operation,))
        for cid in ("410001", "410002"):
            await acquire(s, uid, "真意", cid)
        first = {**blank(), "真意": [item("410001"), item("410002")]}
        await f.import_code(uid, "first", encode(first))
        before = await snapshot(s, uid)
        with pytest.raises(ZhuangpeiFeatureError, match="不足"):
            await f.import_code(uid, "swap-without-stock", encode({**blank(), "真意": list(reversed(first["真意"]))}))
        assert await snapshot(s, uid) == before
    asyncio.run(run())


@pytest.mark.parametrize("section,cid", [("功法", "400001"), ("真意", "410001"), ("气机", "420001"), ("器律", "700001")])
def test_content_uses_combat_public_renderer(services, section, cid):
    value = services.features.zhuangpei.detail(section, cid)
    assert value["name"] and value["lines"]
    assert not any("未支持" in line for line in value["lines"])

# ─────────── 原 tests/test_zhuangpei_codec.py ───────────

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

# ─────────── 原 tests/test_zhuangpei_site.py ───────────

import asyncio
import importlib
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI

from game.features.zhuangpei import ZhuangpeiFeatureError, encode


def _app(services, monkeypatch):
    site = importlib.import_module("game.cmd.通用.装配台.site")
    monkeypatch.setattr(site, "current_game_services", lambda: services)
    app = FastAPI()
    app.include_router(site.router)
    return app


def test_scope_for_unknown_user_is_clean_error(services, monkeypatch):
    """查一个不存在或没公开的用户名 ⇒ 400 + 人话，而不是 500 堆栈。"""
    with HttpClient(_app(services, monkeypatch)) as client:
        response = client.get("/assembly/data?scope=user:no-such-user")
        assert response.status_code == 400
        assert "公开" in response.json()["error"]


def test_content_endpoint_contract(services, monkeypatch):
    with HttpClient(_app(services, monkeypatch)) as client:
        good = client.get(f"/assembly/content?section={quote('功法')}&content_id=400001")
        assert good.status_code == 200
        assert good.json()["name"] and isinstance(good.json()["lines"], list)
        bad_section = client.get(f"/assembly/content?section={quote('不存在的类')}&content_id=400001")
        assert bad_section.status_code == 400
        assert "功法" in bad_section.json()["error"]
        assert client.get(f"/assembly/content?section={quote('功法')}&content_id=999999").status_code == 400
        assert client.get(f"/assembly/content?section={quote('功法')}").status_code == 422


def test_scheme_endpoint_payload_edges(services, monkeypatch):
    with HttpClient(_app(services, monkeypatch)) as client:
        for payload in ({"build": None}, {"code": ""}, {"code": 12}, {}, {"build": blank(), "code": "x"}):
            assert client.post("/assembly/scheme", json=payload).status_code == 400, payload


def test_import_command_format_hint_does_not_write(services, monkeypatch):
    """空参、多参只给格式提示，不产生任何事务。"""
    module = importlib.import_module("game.cmd.通用.装配台")
    monkeypatch.setattr(module, "current_game_services", lambda: services)
    sent: list = []

    async def send(value):
        sent.append(value)

    manager = SimpleNamespace(send=send)

    async def run():
        uid = await player(services)
        before = services.core.database.status().transaction_count
        for index, message in enumerate(("", "   ", "ZP1.abc extra")):
            await module.import_assembly(
                user_id=uid, message=message,
                message_context=SimpleNamespace(request_id=f"format-{index}"), manager=manager,
            )
            assert "格式：导入装配 装配码" in str(sent[-1])
        assert services.core.database.status().transaction_count == before

    asyncio.run(run())


def test_public_toggle_command_cards(services, monkeypatch):
    module = importlib.import_module("game.cmd.通用.装配台")
    monkeypatch.setattr(module, "current_game_services", lambda: services)
    sent: list = []

    async def send(value):
        sent.append(value)

    manager = SimpleNamespace(send=send)

    async def run():
        uid = await player(services)
        await module.toggle_public(user_id=uid, message_context=SimpleNamespace(request_id="pub-1"), manager=manager)
        assert "已公开" in str(sent[-1])
        await module.toggle_public(user_id=uid, message_context=SimpleNamespace(request_id="pub-2"), manager=manager)
        assert "已关闭" in str(sent[-1])

    asyncio.run(run())


@pytest.mark.parametrize("text", ["ZP1.abc", "　", "ZP1.abc extra"])
def test_import_command_error_card_names_the_code(services, monkeypatch, text):
    """非法码一律落错误卡片，且提示里要认得出是"装配码"问题。"""
    module = importlib.import_module("game.cmd.通用.装配台")
    monkeypatch.setattr(module, "current_game_services", lambda: services)
    sent: list = []

    async def send(value):
        sent.append(value)

    async def run():
        uid = await player(services)
        await module.import_assembly(
            user_id=uid, message=text,
            message_context=SimpleNamespace(request_id=f"parse-{abs(hash(text))}"),
            manager=SimpleNamespace(send=send),
        )
        assert "装配码" in str(sent[-1])

    asyncio.run(run())


def test_public_scope_lists_that_users_holdings(services, monkeypatch):
    """公开后按用户名能选到对方的池；关闭后立刻从列表与范围内消失。"""

    async def run():
        uid = await player(services)
        await acquire(services, uid, "功法", "400001")
        await services.features.zhuangpei.toggle_public(uid, "scope-open")
        with HttpClient(_app(services, monkeypatch)) as client:
            data = client.get(f"/assembly/data?scope=user:{uid}").json()
            assert data["scope"] == f"user:{uid}"
            entry = next(e for e in data["entries"] if e["section"] == "功法" and e["id"] == "400001")
            assert entry["quantity"] == 1 and entry["equipped"] == []
            assert f"user:{uid}" in {value["id"] for value in client.get("/assembly/data").json()["scopes"]}
            await services.features.zhuangpei.toggle_public(uid, "scope-close")
            closed = client.get(f"/assembly/data?scope=user:{uid}")
            assert closed.status_code == 400 and "公开" in closed.json()["error"]
            assert f"user:{uid}" not in {value["id"] for value in client.get("/assembly/data").json()["scopes"]}

    asyncio.run(run())


def test_public_scope_keeps_equipped_entry_without_stock(services, monkeypatch):
    """真意按规则会被消耗：装进槽位后库存归零，但条目仍要留在本人清单里。"""

    async def run():
        uid = await player(services)
        content_id = next(iter(services.core.data.entities("真意")))
        await acquire(services, uid, "真意", content_id)
        code = encode({**blank(), "真意": [item(content_id)]})
        await services.features.zhuangpei.import_code(uid, "stock-import", code)
        await services.features.zhuangpei.toggle_public(uid, "stock-open")
        with HttpClient(_app(services, monkeypatch)) as client:
            entries = client.get(f"/assembly/data?scope=user:{uid}").json()["entries"]
            entry = next(e for e in entries if e["section"] == "真意" and e["id"] == content_id)
            assert entry["quantity"] == 0
            assert entry["equipped"] == [1]

    asyncio.run(run())


def test_same_request_id_with_other_code_is_refused(services):
    """同请求编号复用到不同码 ⇒ 明确拒绝，而不是当成重放。"""

    async def run():
        uid = await player(services)
        ids = tuple(services.core.data.entities("功法"))[:2]
        for content_id in ids:
            await acquire(services, uid, "功法", content_id)
        feature = services.features.zhuangpei
        await feature.import_code(uid, "same-request", encode({**blank(), "功法": [item(ids[0])]}))
        with pytest.raises(ZhuangpeiFeatureError, match="同一请求编号"):
            await feature.import_code(uid, "same-request", encode({**blank(), "功法": [item(ids[1])]}))
        # 同一个码重放 ⇒ 幂等回执，不报错
        replay = await feature.import_code(uid, "same-request", encode({**blank(), "功法": [item(ids[0])]}))
        assert replay.replayed is True

    asyncio.run(run())


def test_scheme_rejects_duplicate_and_over_limit(services):
    """整套校验的两条硬边界：超过人物槽位上限、同类里重复装同一内容。"""
    feature = services.features.zhuangpei
    ids = tuple(services.core.data.entities("功法"))
    limits = services.core.character.assembly_limits()
    with pytest.raises(ZhuangpeiFeatureError, match="槽位上限"):
        feature.scheme({**blank(), "功法": [item(ids[0])] * (limits["功法"] + 1)})
    assert limits["功法"] >= 2
    with pytest.raises(ZhuangpeiFeatureError, match="不能重复装配"):
        feature.scheme({**blank(), "功法": [item(ids[0]), item(ids[0])]})
