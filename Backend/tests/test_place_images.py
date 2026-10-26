"""Same-POI photos: no planning writes, no fuzzy lookup, bounded shared work."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_on_demand import client as client
from test_on_demand import seed, snapshot
from test_route_first import db as db

from app.api import place_images
from app.db.models import Trip
from app.services import place_photos as photos
from app.services.place_photos import PhotoLoader


@pytest.fixture(autouse=True)
def isolated_loader(monkeypatch):
    value = PhotoLoader()
    monkeypatch.setattr(place_images, "loader", value)
    return value


def details(monkeypatch, *, raw=None, success=True):
    calls = []

    async def call(server, name, args):
        calls.append((server, name, args))
        data = (
            raw
            if raw is not None
            else {
                "id": args["id"],
                "cityname": "杭州市",
                "photos": [
                    {"url": "https://images.example.com/one.jpg"},
                    {"url": "https://images.example.com/two.jpg"},
                    {"url": "https://images.example.com/three.jpg"},
                ],
            }
        )
        return SimpleNamespace(success=success, content=[{"pois": [data]}])

    monkeypatch.setattr(photos.mcp_client, "call_tool", call)
    return calls


async def request_body(monkeypatch, client):
    browse = await seed(monkeypatch, client)
    return {"plan_version": browse["plan_version"], "evidence_id": "a1"}


async def test_same_id_detail_images_are_read_only_and_cached(monkeypatch, client, db):
    request = await request_body(monkeypatch, client)
    calls = details(monkeypatch)
    before = await snapshot(db)
    first = await client.post("/api/v1/conversations/browse/place-images", json=request)
    second = await client.post("/api/v1/conversations/browse/place-images", json=request)
    assert first.status_code == second.status_code == 200
    result = first.json()
    assert result == second.json() and result["status"] == "ok" and len(result["images"]) == 2
    assert all(
        image["poi_id"] == "a1" and image["source"] == "高德地图 MCP" for image in result["images"]
    )
    assert calls == [("amap", "maps_search_detail", {"id": "a1"})]
    assert await snapshot(db) == before


async def test_existing_images_skip_provider_and_are_limited_to_two(monkeypatch, client, db):
    await request_body(monkeypatch, client)
    async with db() as session:
        trip = (await session.execute(select(Trip))).scalar_one()
        data = deepcopy(trip.plan_json)
        data["evidence"][0]["data"]["image_urls"] = [
            " https://images.example.com/a.jpg ",
            "https://images.example.com/a.jpg",
            "https://images.example.com/b.jpg",
            "https://images.example.com/c.jpg",
        ]
        trip.plan_json = data
        await session.commit()
    version = (await client.get("/api/v1/conversations/browse/trip")).json()["version"]
    calls = details(monkeypatch)
    result = (
        await client.post(
            "/api/v1/conversations/browse/place-images",
            json={"plan_version": version, "evidence_id": "a1"},
        )
    ).json()
    assert result["status"] == "ok" and len(result["images"]) == 2 and not calls
    assert result["images"][0]["url"] == "https://images.example.com/a.jpg"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"plan_version": "0" * 64}, 409),
        ({"evidence_id": "h1"}, 400),
        ({"evidence_id": "weather:1"}, 400),
        ({"poi_id": "arbitrary"}, 422),
    ],
)
async def test_invalid_context_never_queries_provider(monkeypatch, client, change, code):
    request = await request_body(monkeypatch, client)
    calls = details(monkeypatch)
    response = await client.post(
        "/api/v1/conversations/browse/place-images", json={**request, **change}
    )
    assert response.status_code == code and not calls


@pytest.mark.parametrize(
    "raw,success,status",
    [
        ({"id": "different", "photos": ["https://images.example.com/wrong.jpg"]}, True, "empty"),
        (
            {
                "id": "a1",
                "cityname": "成都市",
                "photos": ["https://images.example.com/wrong-city.jpg"],
            },
            True,
            "empty",
        ),
        (
            {
                "id": "a1",
                "business_status": "closed",
                "photos": ["https://images.example.com/closed.jpg"],
            },
            True,
            "empty",
        ),
        ({"id": "a1", "photos": [None, {}, ["bad"], {"url": "javascript:x"}]}, True, "empty"),
        ({"id": "a1"}, False, "unavailable"),
    ],
)
async def test_wrong_id_city_closed_or_unavailable_degrades_without_fuzzy_lookup(
    monkeypatch, client, raw, success, status
):
    request = await request_body(monkeypatch, client)
    calls = details(monkeypatch, raw=raw, success=success)
    result = (await client.post("/api/v1/conversations/browse/place-images", json=request)).json()
    assert result["status"] == status and not result["images"]
    assert len(calls) == 1 and calls[0][2] == {"id": "a1"}


@pytest.mark.parametrize("remove", [False, True])
async def test_update_or_delete_during_fetch_discards_images(monkeypatch, client, db, remove):
    request = await request_body(monkeypatch, client)
    started = asyncio.Event()
    release = asyncio.Event()

    async def call(server, name, args):
        started.set()
        await release.wait()
        return SimpleNamespace(
            success=True,
            content=[{"pois": [{"id": "a1", "photos": ["https://images.example.com/a.jpg"]}]}],
        )

    monkeypatch.setattr(
        photos.mcp_client,
        "call_tool",
        call,
    )
    task = asyncio.create_task(
        client.post("/api/v1/conversations/browse/place-images", json=request)
    )
    await started.wait()
    async with db() as session:
        trip = (await session.execute(select(Trip))).scalar_one()
        if remove:
            await session.delete(trip)
        else:
            data = deepcopy(trip.plan_json)
            data["itinerary"]["days"][0]["theme"] = "new version"
            trip.plan_json = data
        await session.commit()
    release.set()
    assert (await task).status_code == (404 if remove else 409)


async def test_loader_deduplicates_and_serializes_distinct_pois(monkeypatch):
    loader = PhotoLoader()
    calls = []
    active = 0
    maximum = 0
    release = asyncio.Event()
    started = asyncio.Event()

    async def call(server, name, args):
        nonlocal active, maximum
        calls.append(args["id"])
        active += 1
        maximum = max(maximum, active)
        started.set()
        await release.wait()
        active -= 1
        return SimpleNamespace(
            success=True,
            content=[
                {"pois": [{"id": args["id"], "photos": ["https://images.example.com/a.jpg"]}]}
            ],
        )

    monkeypatch.setattr(photos.mcp_client, "call_tool", call)
    tasks = [asyncio.create_task(loader.get("杭州", ref)) for ref in ["a1", "a1", "a2", "a3"]]
    await started.wait()
    release.set()
    results = await asyncio.gather(*tasks)
    assert len(calls) == 3 and maximum == 1 and all(result.status == "ok" for result in results)


async def test_one_cancelled_waiter_does_not_cancel_shared_lookup(monkeypatch):
    loader = PhotoLoader()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def call(server, name, args):
        calls.append(args)
        started.set()
        await release.wait()
        return SimpleNamespace(
            success=True,
            content=[{"pois": [{"id": "a1", "photos": ["https://images.example.com/a.jpg"]}]}],
        )

    monkeypatch.setattr(photos.mcp_client, "call_tool", call)
    first = asyncio.create_task(loader.get("杭州", "a1"))
    second = asyncio.create_task(loader.get("杭州市", "a1"))
    await started.wait()
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    release.set()
    assert (await second).status == "ok" and len(calls) == 1


async def test_all_cancelled_waiters_stop_background_work(monkeypatch):
    loader = PhotoLoader()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def call(server, name, args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(photos.mcp_client, "call_tool", call)
    task = asyncio.create_task(loader.get("杭州", "a1"))
    await started.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert cancelled.is_set() and not loader._state().jobs


async def test_short_failure_cache_expires_and_queued_work_is_bounded(monkeypatch):
    loader = PhotoLoader()
    clock = [100.0]
    calls = []
    monkeypatch.setattr(photos, "monotonic", lambda: clock[0])

    async def failure(server, name, args):
        calls.append(args)
        return SimpleNamespace(success=False)

    monkeypatch.setattr(photos.mcp_client, "call_tool", failure)
    assert (await loader.get("杭州", "a1")).status == "unavailable"
    await loader.get("杭州", "a1")
    assert len(calls) == 1
    clock[0] += 16
    await loader.get("杭州", "a1")
    assert len(calls) == 2
    loader.JOB_LIMIT = 1
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait(server, name, args):
        started.set()
        await release.wait()
        return SimpleNamespace(success=False)

    monkeypatch.setattr(photos.mcp_client, "call_tool", wait)
    pending = asyncio.create_task(loader.get("杭州", "busy"))
    await started.wait()
    assert (await loader.get("杭州", "other")).status == "unavailable"
    release.set()
    await pending


@pytest.mark.parametrize("ref", ["a1", "r1", "h1"])
def test_used_attraction_restaurant_and_hotel_references_are_accepted(ref):
    from test_closed_loop import candidate, evidence

    from app.api.place_images import resolve_place

    city, data = resolve_place(
        {"itinerary": candidate(), "evidence": [e.model_dump() for e in evidence()]}, ref
    )
    assert city == "杭州市" and data["id"] == ref


async def test_optional_timeout_degrades_and_does_not_poison_future_jobs(monkeypatch):
    loader = PhotoLoader()
    loader.FETCH_TIMEOUT = 0.01
    cancelled = asyncio.Event()

    async def call(server, name, args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(photos.mcp_client, "call_tool", call)
    result = await loader.get("杭州", "slow")
    assert result.status == "unavailable" and cancelled.is_set() and not loader._state().jobs
    # Immediate waiter timeout may cancel a job before its coroutine starts.
    loader = PhotoLoader()
    loader.WAIT_TIMEOUT = 0
    assert (await loader.get("杭州", "queued")).status == "unavailable"
    assert not loader._state().jobs


async def test_completed_cache_has_bounded_size_and_positive_entries_expire(monkeypatch):
    loader = PhotoLoader()
    clock = [1.0]
    calls = []
    monkeypatch.setattr(photos, "monotonic", lambda: clock[0])
    monkeypatch.setattr(PhotoLoader, "CACHE_LIMIT", 2)

    async def call(server, name, args):
        calls.append(args["id"])
        return SimpleNamespace(
            success=True,
            content=[
                {"pois": [{"id": args["id"], "photos": ["https://images.example.com/a.jpg"]}]}
            ],
        )

    monkeypatch.setattr(photos.mcp_client, "call_tool", call)
    for ref in ("one", "two", "three"):
        await loader.get("杭州", ref)
    assert len(loader._state().cache) == 2
    await loader.get("杭州", "one")
    assert calls == ["one", "two", "three", "one"]
    clock[0] += 301
    await loader.get("杭州", "one")
    assert calls[-2:] == ["one", "one"]
