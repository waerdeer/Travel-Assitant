"""Bounded same-POI photo enrichment, separate from planning and persistence."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal

from app.graph.anchors import same_city
from app.graph.geography import detail_place
from app.graph.place_policy import unavailable_place
from app.graph.tools import AMAP_SERVER, TOOL_DETAIL
from app.mcp.registry import mcp_client
from app.services.images import poi_images


@dataclass(frozen=True)
class PhotoResult:
    status: Literal["ok", "empty", "unavailable"]
    urls: tuple[str, ...] = ()


@dataclass
class Job:
    task: asyncio.Task
    waiters: int = 0


@dataclass
class LoaderState:
    slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    cache: OrderedDict = field(default_factory=OrderedDict)
    jobs: dict = field(default_factory=dict)


class PhotoLoader:
    """One physical lookup at a time; duplicate waiters share a cancellable job.

    State is local to the event loop. Completed cache has at most 128 entries;
    positive/empty/unavailable results live for 300/60/15 seconds. At most 16
    unique jobs can be queued, with a 12s caller deadline and 8s physical timeout.
    When all callers leave, work is cancelled rather than silently continuing.
    """

    CACHE_LIMIT = 128
    JOB_LIMIT = 16
    WAIT_TIMEOUT = 12
    FETCH_TIMEOUT = 8

    def __init__(self):
        self._loop = None
        self._current = None

    def _state(self):
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._loop = loop
            self._current = LoaderState()
        return self._current

    @staticmethod
    def _remember(state, key, result):
        ttl = {"ok": 300, "empty": 60, "unavailable": 15}[result.status]
        state.cache[key] = (monotonic() + ttl, result)
        state.cache.move_to_end(key)
        while len(state.cache) > PhotoLoader.CACHE_LIMIT:
            state.cache.popitem(last=False)

    async def _fetch(self, state, key, city, poi_id):
        try:
            async with state.slots:
                try:
                    result = await asyncio.wait_for(
                        mcp_client.call_tool(AMAP_SERVER, TOOL_DETAIL, {"id": poi_id}),
                        timeout=self.FETCH_TIMEOUT,
                    )
                    if not result.success:
                        photos = PhotoResult("unavailable")
                    else:
                        poi = detail_place(result.content, poi_id)
                        if (
                            not poi
                            or unavailable_place(poi)
                            or (
                                poi.get("cityname")
                                and (
                                    not isinstance(poi["cityname"], str)
                                    or not same_city(poi["cityname"], city)
                                )
                            )
                        ):
                            photos = PhotoResult("empty")
                        else:
                            urls = tuple(poi_images(poi)[:2])
                            photos = PhotoResult("ok" if urls else "empty", urls)
                except Exception:
                    photos = PhotoResult("unavailable")
                self._remember(state, key, photos)
                return photos
        finally:
            state.jobs.pop(key, None)

    async def get(self, city: str, poi_id: str) -> PhotoResult:
        state = self._state()
        key = (city.strip().removesuffix("市"), poi_id)
        cached = state.cache.get(key)
        if cached:
            if cached[0] > monotonic():
                state.cache.move_to_end(key)
                return cached[1]
            state.cache.pop(key, None)
        job = state.jobs.get(key)
        if job is None:
            if len(state.jobs) >= self.JOB_LIMIT:
                return PhotoResult("unavailable")
            job = Job(asyncio.create_task(self._fetch(state, key, city, poi_id)))
            state.jobs[key] = job

            def finished(task):
                current = state.jobs.get(key)
                if current and current.task is task:
                    state.jobs.pop(key, None)

            job.task.add_done_callback(finished)
        job.waiters += 1
        try:
            return await asyncio.wait_for(asyncio.shield(job.task), timeout=self.WAIT_TIMEOUT)
        except TimeoutError:
            return PhotoResult("unavailable")
        finally:
            job.waiters -= 1
            if not job.waiters and not job.task.done():
                job.task.cancel()
                # Protect retries during a provider outage or a saturated queue.
                self._remember(state, key, PhotoResult("unavailable"))
                await asyncio.gather(job.task, return_exceptions=True)
