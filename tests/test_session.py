"""Synthetic operation ownership and manual session/deadline checks."""
import asyncio
from dataclasses import replace

import pytest

from custom_components.xparkle_rvlevel.protocol import decode
from custom_components.xparkle_rvlevel.session import Limits, Session

PAYLOAD = bytes((0, 0, 9, 1, 0, 50, 100))
FAST = Limits(inactivity=600, poll_interval=0.002, connect=0.05, read=0.05,
              settle=0.02, disconnect=0.03)


async def until(predicate):
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("synthetic_condition_not_reached")


class Clock:
    value = 0
    def __call__(self):
        return self.value


class FakeTransport:
    def __init__(self):
        self.is_connected = False
        self.cleanup_confirmed = True
        self.calls = []
        self.read_times = []
        self.payload = PAYLOAD
        self.connect_block = self.read_block = self.disconnect_block = None
        self.ignore_cancel = False
        self.disconnect_error = False
        self.gatt = True

    async def _block(self, event):
        if event is None:
            return
        while not event.is_set():
            try:
                await event.wait()
            except asyncio.CancelledError:
                if not self.ignore_cancel:
                    raise

    async def connect(self):
        self.calls.append("connect")
        await self._block(self.connect_block)
        self.is_connected = True

    def compatible(self):
        return self.gatt

    async def read(self):
        self.calls.append("read")
        self.read_times.append(asyncio.get_running_loop().time())
        await self._block(self.read_block)
        return self.payload

    async def disconnect(self):
        self.calls.append("disconnect")
        await self._block(self.disconnect_block)
        if self.disconnect_error:
            raise RuntimeError("PRIVATE_TRANSPORT_SENTINEL")
        self.is_connected = False


def test_decoder_prefix_flags_invalid_battery_and_truncation():
    result = decode(PAYLOAD + b"extra")
    assert (result.pitch_magnitude, result.roll_magnitude, result.battery) == (0.09, 0.5, 100)
    assert result.uphill is False and result.left_tilt is True
    assert decode(bytes((1, 1, 2, 0, 0, 5, 255))).battery is None
    for payload in (b"", PAYLOAD[:6], bytes((2, 0, 0, 0, 0, 0, 100)), bytes((0, 0, 0, 2, 0, 0, 100))):
        with pytest.raises(ValueError, match="unsupported_payload"):
            decode(payload)


async def test_startup_renew_off_and_polling_do_not_create_background_connection():
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST)
    assert session.safe and session.status == "idle" and not session.renew()
    await asyncio.sleep(0)
    assert transport.calls == []
    assert await session.start()
    assert not await session.start()  # Repeated admission cannot connect twice.
    await until(lambda: session.read_count >= 3)
    assert session.fresh and session.status == "measuring"
    assert transport.calls.count("connect") == 1
    assert set(transport.calls) <= {"connect", "read", "disconnect"}
    assert all(b-a >= FAST.poll_interval for a, b in zip(transport.read_times, transport.read_times[1:]))
    assert await session.stop()
    reads = session.read_count
    await asyncio.sleep(0.01)
    assert session.read_count == reads and not session.fresh and session.safe
    assert not session.renew() and session.status == "idle"


async def test_polls_never_renew_600_second_deadline_and_exact_expiry():
    clock = Clock()
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST, clock=clock)
    await session.start()
    await until(lambda: session.read_count >= 3)
    assert session.deadline == 600
    clock.value = 599.999
    session._renewed.set()  # Wake the controllable clock, not a user renewal.
    await asyncio.sleep(0)
    assert session.requested and session.deadline == 600
    clock.value = 600
    session._renewed.set()
    await until(lambda: session.safe)
    assert session.reason == "inactivity_timeout" and not session.renew()
    assert transport.calls.count("connect") == 1


async def test_only_explicit_renew_extends_deadline_and_expired_renew_does_not_restart():
    clock = Clock()
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST, clock=clock)
    await session.start()
    await until(lambda: session.read_count)
    clock.value = 590
    assert session.renew() and session.deadline == 1190
    clock.value = 600
    session._renewed.set()
    await until(lambda: session.read_count >= 2)
    assert session.requested
    clock.value = 1190
    assert not session.renew()
    await until(lambda: session.safe)
    assert not session.requested and transport.calls.count("connect") == 1


async def test_stop_before_worker_runs_makes_no_connection():
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST)
    await session.start()
    assert await session.stop()
    assert transport.calls == []


@pytest.mark.parametrize("where", ["connect", "read"])
async def test_stop_interrupts_operation_and_blocks_successor_until_closed(where):
    transport = FakeTransport()
    setattr(transport, where + "_block", asyncio.Event())
    session = Session(lambda: transport, limits=FAST)
    await session.start()
    await until(lambda: where in transport.calls)
    stop = asyncio.create_task(session.stop())
    await asyncio.sleep(0)
    assert not await session.start()
    assert await stop
    assert not session.pending_operations and session.safe
    assert transport.calls[-1] == "disconnect"


async def test_late_connect_is_retained_reconciled_and_cannot_revive_a_successor():
    old = FakeTransport()
    old.connect_block = asyncio.Event()
    old.ignore_cancel = True
    new = FakeTransport()
    transports = iter((old, new))
    session = Session(lambda: next(transports), limits=FAST)
    await session.start()
    await until(lambda: "connect" in old.calls)
    assert not await session.stop()
    assert session.status == "cleanup_unknown" and session.pending_operations == 1
    assert not await session.start()
    old.connect_block.set()
    await until(lambda: session.safe)
    assert not old.is_connected and old.calls == ["connect", "disconnect"]
    assert await session.start()
    await until(lambda: session.read_count)
    assert session.connected and new.is_connected
    assert await session.stop()


async def test_late_read_cannot_publish_after_stop():
    transport = FakeTransport()
    transport.read_block = asyncio.Event()
    transport.ignore_cancel = True
    session = Session(lambda: transport, limits=FAST)
    await session.start()
    await until(lambda: "read" in transport.calls)
    assert not await session.stop()
    transport.read_block.set()
    await until(lambda: session.safe)
    assert session.read_count == 0 and session.measurement is None


async def test_repeated_worker_and_caller_cancellation_do_not_cancel_disconnect():
    transport = FakeTransport()
    transport.disconnect_block = asyncio.Event()
    session = Session(lambda: transport, limits=replace(FAST, disconnect=0.2))
    await session.start()
    await until(lambda: session.read_count)
    stop = asyncio.create_task(session.stop())
    await until(lambda: "disconnect" in transport.calls)
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    session._runner.cancel()
    await asyncio.sleep(0)
    session._runner.cancel()
    assert not await session.start()
    transport.disconnect_block.set()
    await until(lambda: session.safe)
    assert transport.calls.count("disconnect") == 1


@pytest.mark.parametrize("failure", ["gatt", "payload", "read_timeout", "connection_lost"])
async def test_errors_end_session_without_retry_and_invalidate_measurements(failure):
    transport = FakeTransport()
    if failure == "gatt": transport.gatt = False
    if failure == "payload": transport.payload = b"bad"
    if failure == "read_timeout": transport.read_block = asyncio.Event()
    session = Session(lambda: transport, limits=FAST)
    await session.start()
    if failure == "connection_lost":
        await until(lambda: session.read_count)
        transport.is_connected = False
    await until(lambda: session.safe)
    assert session.status == "error" and not session.fresh
    if failure == "gatt":
        assert transport.calls == ["connect", "disconnect"] and session.read_count == 0
    assert transport.calls.count("connect") == 1
    assert not session.requested


async def test_failed_disconnect_never_claims_safe_or_allows_successor():
    transport = FakeTransport()
    transport.disconnect_error = True
    session = Session(lambda: transport, limits=FAST)
    await session.start()
    await until(lambda: session.read_count)
    assert not await session.stop()
    assert session.status == "cleanup_unknown" and not await session.start()
    await until(lambda: not session.busy)
    assert transport.calls.count("disconnect") <= 2
    assert not await session.shutdown()
    assert "PRIVATE" not in session.reason
    transport.is_connected = False  # Simulate external backend reconciliation.
    assert await session.stop()


async def test_shutdown_blocks_future_start_and_failing_listener_cannot_prevent_cleanup():
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST)
    def bad_listener(): raise RuntimeError("PRIVATE_LISTENER_SENTINEL")
    session.listen(bad_listener)
    await session.start()
    await until(lambda: session.read_count)
    assert await session.shutdown()
    assert session.safe and not await session.start()


def test_fixed_production_limits():
    assert Limits() == Limits(inactivity=600, poll_interval=0.5, connect=20, read=5, settle=5, disconnect=10)


async def test_scheduled_refresh_one_read_immediate_close_and_no_angle_freshness():
    transport = FakeTransport()
    session = Session(lambda: transport, limits=FAST)
    assert await session.refresh_battery()
    assert not await session.refresh_battery() and not await session.start()
    assert not session.renew()
    await until(lambda: session.safe)
    assert transport.calls == ["connect","read","disconnect"]
    assert session.battery == 100 and session.battery_received_at is not None
    assert not session.fresh and session.status == "idle"


async def test_invalid_battery_or_failed_refresh_never_retimestamp_retained_value():
    first, invalid = FakeTransport(), FakeTransport()
    invalid.payload = bytes((0,0,9,1,0,50,255))
    transports = iter((first,invalid))
    session = Session(lambda: next(transports), limits=FAST)
    await session.refresh_battery()
    await until(lambda: session.safe)
    timestamp = session.battery_received_at
    await session.refresh_battery()
    await until(lambda: session.safe)
    assert session.battery == 100 and session.battery_received_at == timestamp
    await session.refresh_battery()  # Exhausted fake factory fails without another connect.
    await until(lambda: session.safe)
    assert session.battery == 100 and session.battery_received_at == timestamp


async def test_shutdown_during_scheduled_read_settles_and_closes():
    transport = FakeTransport()
    transport.read_block = asyncio.Event()
    session = Session(lambda: transport, limits=FAST)
    await session.refresh_battery()
    await until(lambda: "read" in transport.calls)
    assert await session.shutdown()
    assert session.read_count == 0 and session.battery is None and session.safe
    assert transport.calls == ["connect","read","disconnect"]


async def test_proxy_cleanup_unconfirmed_blocks_both_manual_and_scheduled_admission():
    transport = FakeTransport()
    transport.cleanup_confirmed = False
    session = Session(lambda: transport, limits=FAST)
    await session.start()
    await until(lambda: session.read_count)
    assert not await session.stop()
    assert session.status == "cleanup_unknown" and not session.connected
    assert not await session.start() and not await session.refresh_battery()
    transport.cleanup_confirmed = True
    assert await session.stop()


async def test_stubborn_disconnect_stays_owned_and_late_completion_is_reconciled():
    transport = FakeTransport()
    transport.disconnect_block = asyncio.Event()
    transport.ignore_cancel = True
    session = Session(lambda: transport, limits=FAST)
    await session.start()
    await until(lambda: session.read_count)
    assert not await session.stop()
    assert session.pending_operations and session.status == "cleanup_unknown"
    assert not await session.refresh_battery()
    transport.disconnect_block.set()
    await until(lambda: session.safe)
    assert transport.calls.count("disconnect") == 1
