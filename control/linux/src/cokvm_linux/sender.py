"""Send VSS frames with keyboard priority and motion coalescing."""

from __future__ import annotations

import asyncio
import logging
from collections import deque

log = logging.getLogger(__name__)


class FrameSender:
    def __init__(self, transport, interval: float = 0.008):
        self._transport = transport
        self._interval = interval
        self._keyboard: deque[bytes] = deque()
        self._discrete: deque[bytes] = deque()
        self._motion: bytes | None = None
        self._event = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            raise RuntimeError("sender already started")
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        self._idle.set()

    def submit_keyboard(self, frame: bytes) -> None:
        self._keyboard.append(frame)
        self._wake()

    def submit_discrete(self, frame: bytes) -> None:
        self._discrete.append(frame)
        self._wake()

    def submit_motion(self, frame: bytes) -> None:
        self._motion = frame
        self._wake()

    def clear(self) -> None:
        self._keyboard.clear()
        self._discrete.clear()
        self._motion = None
        # If the worker is running it will empty the queues and set _idle
        # after the current in-flight send; forcing it here would let a
        # subsequent drain() return before that send completes.  When the
        # worker was never started nothing else will set it, so do it here.
        if self._task is None:
            self._idle.set()

    async def drain(self, timeout: float = 0.2) -> None:
        try:
            await asyncio.wait_for(self._idle.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    def _wake(self) -> None:
        self._idle.clear()
        self._event.set()

    async def _run(self) -> None:
        while True:
            await self._event.wait()
            while self._keyboard or self._discrete or self._motion is not None:
                if self._keyboard:
                    frame = self._keyboard.popleft()
                elif self._discrete:
                    frame = self._discrete.popleft()
                else:
                    if self._interval:
                        await asyncio.sleep(self._interval)
                    frame = self._motion
                    if frame is None:
                        continue
                    self._motion = None
                try:
                    log.debug("frame %s", frame.hex(" "))
                    await self._transport.send(frame)
                except Exception:
                    log.exception("frame send failed")
            self._event.clear()
            self._idle.set()
