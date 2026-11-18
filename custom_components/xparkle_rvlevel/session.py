"""Manual, expiring measurement sessions without background reconnects."""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from collections import deque
from uuid import uuid4
from typing import Any, Protocol

from .protocol import Measurement, decode

SPEED_STAGES = (1.0, 0.5, 0.25, 0.1)
SPEED_READS_PER_STAGE = 8


class Transport(Protocol):
    """Only operations permitted by the read-only session."""

    @property
    def is_connected(self) -> bool: ...
    @property
    def cleanup_confirmed(self) -> bool: ...
    async def connect(self) -> None: ...
    def compatible(self) -> bool: ...
    async def read(self) -> bytes: ...
    async def disconnect(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Limits:
    """Fixed production limits; injection permits fast synthetic deadlines."""

    inactivity: float = 600
    poll_interval: float = 0.5
    connect: float = 20
    read: float = 5
    settle: float = 5
    disconnect: float = 10


class _Stopped(Exception):
    """The user or watchdog ended this session."""


class Session:
    """Own every operation until it settles, including late cancellation."""

    def __init__(
        self, factory: Callable[[], Transport], *, limits: Limits = Limits(),
        clock: Callable[[], float] = time.monotonic,
        create_task: Callable[[Coroutine[Any, Any, Any]], asyncio.Task] = asyncio.create_task,
        admission_enabled: bool = True,
    ) -> None:
        self.factory = factory
        self.limits = limits
        self.clock = clock
        self.create_task = create_task
        self.status = "idle"
        self.reason = "not_started"
        self.requested = False
        self.deadline: float | None = None
        self.measurement: Measurement | None = None
        self.battery: int | None = None
        self.battery_received_at: datetime | None = None
        self.mode = "manual"
        self.received_at: datetime | None = None
        self.received_monotonic: float | None = None
        self.read_count = 0
        self.connection_attempts = 0
        self.transport: Transport | None = None
        self._runner: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._reconciler: asyncio.Task | None = None
        self._operations: set[asyncio.Task] = set()
        self._stop = asyncio.Event()
        self._renewed = asyncio.Event()
        self._listeners: set[Callable[[], None]] = set()
        self._disconnect_attempts = 0
        self._closed = False
        self.admission_enabled = admission_enabled
        self.read_durations = deque(maxlen=256)
        self.sample_intervals = deque(maxlen=256)
        self._sample_sequence = 0
        self.identifier = uuid4().hex
        self._stale_handle = None
        self.speed_report = []
        self._diagnostic_pending = False

    async def test_update_speed(self):
        """One explicit, fixed, finite read-only diagnostic; never a reconnect."""
        if not self._start("speed_test"):
            return None
        self._diagnostic_pending = True
        owned_runner = self._runner
        try:
            try:
                await asyncio.shield(owned_runner)
            except BaseException:
                if self._runner is owned_runner:
                    await self.stop("speed_test_cancelled")
                raise
            return {"complete": self.reason == "speed_test_complete" and self.safe,
                "cleanup_confirmed": self.safe, "connection_attempts": self.connection_attempts,
                "completed_reads": self.read_count, "read_budget": 32,
                "read_deadline_seconds": 40, "stop_reason": self.reason,
                "stages": self.speed_report,
                "measures": "host_GATT_read_timing_not_physical_or_internal_sample_latency"}
        finally:
            self._diagnostic_pending = False

    @property
    def fresh_timeout(self) -> float:
        return max(1.0, min(10.0, self.limits.poll_interval * 3))

    def listen(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _emit(self) -> None:
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:
                # A failing UI listener must never prevent link cleanup.
                continue

    @property
    def connected(self) -> bool:
        if self.transport is None:
            return False
        try:
            return self.transport.is_connected
        except Exception:
            return True  # Unknown link state must block a successor.

    @property
    def pending_operations(self) -> int:
        return sum(not task.done() for task in self._operations)

    @property
    def busy(self) -> bool:
        return bool((self._runner and not self._runner.done()) or
                    (self._reconciler and not self._reconciler.done()))

    @property
    def safe(self) -> bool:
        return not self.busy and not self.pending_operations and not self.connected and self.cleanup_confirmed

    @property
    def cleanup_confirmed(self) -> bool:
        if self.transport is None:
            return True
        try:
            return self.transport.cleanup_confirmed is True
        except Exception:
            return False

    @property
    def fresh(self) -> bool:
        return bool(self.mode == "manual" and self.requested and self.status == "measuring" and self.connected
                    and self.received_monotonic is not None
                    and 0 <= self.clock() - self.received_monotonic <= self.fresh_timeout)

    @property
    def expires_at(self) -> datetime | None:
        if self.mode != "manual" or not self.requested or self.deadline is None:
            return None
        from datetime import timedelta
        return datetime.now(timezone.utc) + timedelta(seconds=max(0, self.deadline - self.clock()))

    async def start(self) -> bool:
        """Only this explicit action can start a new connection."""
        return self._start("manual")

    async def refresh_battery(self) -> bool:
        """Admit one scheduled read, or discard the tick when already busy."""
        return self._start("battery_refresh")

    def _start(self, mode: str) -> bool:
        if self._closed or self._diagnostic_pending or not self.admission_enabled or not self.safe:
            return False
        self.mode = mode
        self.requested = True
        self.status = "connecting"
        self.reason = "started"
        self.measurement = None
        self.transport = None
        self.received_at = self.received_monotonic = None
        self.read_count = self.connection_attempts = self._disconnect_attempts = 0
        self.read_durations.clear()
        self.sample_intervals.clear()
        self.speed_report = [{"interval_seconds": interval, "completed_reads": 0,
                              "read_duration_seconds": [], "start_spacing_seconds": []}
                             for interval in SPEED_STAGES] if mode == "speed_test" else []
        self.deadline = self.clock() + (self.limits.inactivity if mode == "manual" else
                                       40 if mode == "speed_test" else
                                       self.limits.connect + self.limits.read)
        self._stop.clear()
        self._renewed.clear()
        self._runner = self.create_task(self._run())
        self._runner.add_done_callback(self._worker_done)
        self._emit()
        return True

    def renew(self) -> bool:
        """Never start an inactive/expired session or renew on a poll."""
        if self.mode != "manual" or not self.requested or self._stop.is_set() or self.deadline is None:
            return False
        if self.clock() >= self.deadline:
            self._request_stop("inactivity_timeout")
            return False
        self.deadline = self.clock() + self.limits.inactivity
        self._renewed.set()
        self._emit()
        return True

    def _request_stop(self, reason: str) -> None:
        if not self._stop.is_set():
            self.reason = reason
        self.requested = False
        self._stop.set()
        self._renewed.set()
        if self.busy:
            self.status = "stopping"
        self._emit()

    async def stop(self, reason: str = "user_stop") -> bool:
        """Signal promptly; caller cancellation cannot cancel owned cleanup."""
        self._request_stop(reason)
        if self._runner and not self._runner.done():
            await asyncio.wait({self._runner}, timeout=self.limits.settle + self.limits.disconnect + 1)
        self._schedule_reconcile()
        if self._reconciler and not self._reconciler.done():
            await asyncio.wait({self._reconciler}, timeout=self.limits.disconnect + 1)
        return self.safe

    async def shutdown(self) -> bool:
        self._closed = True
        return await self.stop("shutdown")

    def _operation_task(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._operations.add(task)
        def completed(done):
            self._operations.discard(done)
            if not done.cancelled():
                done.exception()  # Do not log arbitrary transport error strings.
            self._schedule_reconcile()
        task.add_done_callback(completed)
        return task

    async def _execute(self, coroutine, timeout: float):
        if self._stop.is_set() or not self.requested or self.clock() >= self.deadline:
            coroutine.close()
            if not self._stop.is_set():
                self._request_stop("speed_test_timeout" if self.mode == "speed_test" else "inactivity_timeout")
            raise _Stopped()
        task = self._operation_task(coroutine)
        stopped = asyncio.create_task(self._stop.wait())
        try:
            done, _ = await asyncio.wait({task, stopped}, timeout=timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
            if self._stop.is_set():
                raise _Stopped()
            if task not in done:
                raise TimeoutError()
            return task.result()
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)
            if not task.done():
                task.cancel()

    async def _watch(self) -> None:
        while self.requested:
            self._renewed.clear()
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                self._request_stop("speed_test_timeout" if self.mode == "speed_test" else "inactivity_timeout")
                return
            try:
                await asyncio.wait_for(self._renewed.wait(), remaining)
            except TimeoutError:
                pass

    async def _settle_operations(self) -> bool:
        tasks = {task for task in self._operations if not task.done()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=self.limits.settle)
        return not self.pending_operations

    async def _disconnect(self) -> None:
        if self.transport is None or self._disconnect_attempts >= 2:
            return
        self._disconnect_attempts += 1
        task = self._operation_task(self.transport.disconnect())
        done, _ = await asyncio.wait({task}, timeout=self.limits.disconnect)
        if task not in done:
            task.cancel()

    async def _cleanup(self) -> None:
        if self._stale_handle:
            self._stale_handle.cancel()
            self._stale_handle = None
        if self._watchdog:
            self._watchdog.cancel()
            await asyncio.gather(self._watchdog, return_exceptions=True)
        if await self._settle_operations():
            # Also call disconnect after a failed/cancelled connect whose
            # backend state is not yet reflected by is_connected.
            await self._disconnect()
        self._finish_state()

    def _finish_state(self) -> None:
        if self.pending_operations or self.connected or not self.cleanup_confirmed:
            self.status = "cleanup_unknown"
        elif self.reason in ("user_stop", "inactivity_timeout", "shutdown", "battery_refresh_complete", "speed_test_complete"):
            self.status = "idle"
        else:
            self.status = "error"
        self._emit()

    def _worker_done(self, task) -> None:
        if not task.cancelled():
            task.exception()
        self._schedule_reconcile()

    def _schedule_reconcile(self) -> None:
        if self.status != "cleanup_unknown" or self.busy or self.pending_operations:
            return
        self._reconciler = self.create_task(self._reconcile())

    async def _reconcile(self) -> None:
        # At most one additional disconnect handles a late backend completion.
        if self.connected:
            await self._disconnect()
        self._finish_state()

    async def _run(self) -> None:
        self._watchdog = asyncio.create_task(self._watch())
        try:
            if not self.requested or self._stop.is_set():
                return
            self.transport = self.factory()
            self.connection_attempts = 1
            await self._execute(self.transport.connect(), self.limits.connect)
            if not self.transport.compatible():
                self.reason = "incompatible_gatt"
                return
            self.status = "measuring"
            stage_previous = {}
            while self.requested and not self._stop.is_set():
                if self.clock() >= self.deadline:
                    self._request_stop("speed_test_timeout" if self.mode == "speed_test" else "inactivity_timeout")
                    break
                if not self.connected:
                    self.reason = "connection_lost"
                    break
                started = self.clock()
                data = await self._execute(self.transport.read(), self.limits.read)
                if not self.requested or self._stop.is_set() or self.clock() >= self.deadline:
                    if not self._stop.is_set():
                        self._request_stop("speed_test_timeout" if self.mode == "speed_test" else "inactivity_timeout")
                    break
                self.measurement = decode(bytes(data))
                completed = self.clock()
                self.read_durations.append(max(0.0, completed - started))
                if self.received_monotonic is not None:
                    self.sample_intervals.append(max(0.0, completed - self.received_monotonic))
                self._sample_sequence += 1
                if self.mode == "speed_test":
                    index = self.read_count // SPEED_READS_PER_STAGE
                    stage = self.speed_report[index]
                    stage["completed_reads"] += 1
                    stage["read_duration_seconds"].append(max(0.0, completed - started))
                    if index in stage_previous:
                        stage["start_spacing_seconds"].append(max(0.0, started - stage_previous[index]))
                    stage_previous[index] = started
                self.received_monotonic = self.clock()
                self.received_at = datetime.now(timezone.utc)
                self.read_count += 1
                if self.measurement.battery is not None:
                    self.battery = self.measurement.battery
                    self.battery_received_at = self.received_at
                self._emit()
                if self.mode == "manual":
                    if self._stale_handle:
                        self._stale_handle.cancel()
                    self._stale_handle = asyncio.get_running_loop().call_later(
                        self.fresh_timeout + 0.001, self._emit)
                if self.mode == "speed_test" and self.read_count >= 32:
                    self._request_stop("speed_test_complete")
                    break
                if self.mode == "battery_refresh":
                    self.reason = "battery_refresh_complete"
                    break
                try:
                    # Target start-to-start cadence, never queue missed slots.
                    # A slow backend still gets a small cooperative quiet gap.
                    interval = (SPEED_STAGES[self.read_count // SPEED_READS_PER_STAGE]
                                if self.mode == "speed_test" else self.limits.poll_interval)
                    delay = max(min(0.02, interval), interval - (self.clock() - started))
                    await asyncio.wait_for(self._stop.wait(), delay)
                except TimeoutError:
                    pass
        except _Stopped:
            pass
        except asyncio.CancelledError:
            self.reason = "cancelled"
        except TimeoutError:
            self.reason = "operation_timeout"
        except ValueError:
            self.reason = "unsupported_payload"
        except Exception:
            self.reason = "connection_or_read_error"
        finally:
            self.requested = False
            self._stop.set()
            self.status = "stopping"
            self._emit()
            # Separate owned cleanup survives repeated cancellation of worker.
            cleanup = asyncio.create_task(self._cleanup())
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
            cleanup.result()
