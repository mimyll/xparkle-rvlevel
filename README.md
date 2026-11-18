# Xparkle RV level

![Xparkle icon](custom_components/xparkle_rvlevel/brand/icon.png)

An independent, read-only Home Assistant integration for compatible Xparkle RV level sensors. It provides manually controlled measurements, optional scheduled battery reads and advisory levelling estimates. It is not affiliated with the device manufacturer.

**Early 0.5.0 release.** Bluetooth compatibility is deliberately restricted to the runtime matrix below. Physical direction mapping, angle accuracy, sensor-internal sample age, movement-to-display latency and battery lifetime are not established by this release.

## Install and update

1. In Home Assistant 2026.11, open **Settings → Marketplace → Add from link**, and add `https://github.com/mimyll/xparkle-rvlevel` as an integration. Older HACS installations use **Custom repositories → Integration**, but this release itself requires the supported Home Assistant runtime below.
2. Download the published release, then follow any normal restart prompt.
3. Open **Settings → Devices & services → Add integration → Xparkle RV level**. Enter the Bluetooth address and exact discovered `RVLevel-` or `RVbalance-` name privately. Setup binds the target without connecting.
4. Close the phone application before starting measurements through HA.

The public repository uses the standard `custom_components/xparkle_rvlevel/` layout. Marketplace installs only that component. It discovers published GitHub releases and exposes an update entity under **Settings → Updates**. Repositories added by link need HA's GitHub connection for scheduled update discovery; this integration never requests a token or downloads its own code.

### Updating an existing installation

Before updating, turn Measurement off and confirm **Session status: idle**, **Connection: off**, and diagnostics **cleanup_confirmed: true**, with no pending owned work. Disable the existing integration and verify it unloaded successfully. Keep a component-only copy of the old source outside `custom_components` and record current options. Then use Marketplace to download the release, check HA configuration, and perform a normal restart while the entry remains disabled. Enable the same entry afterward. Do not remove/re-add it: upgrades retain the existing entry, entity IDs, options, battery cache and history.

Source replacement is not safe while a session or uncertain cleanup remains active. Marketplace's update notification alone does not establish those prerequisites. Version 0.5 does not change the native option schema or any existing entity identity. Measurement stays off after restart; periodic battery work is first due one full configured interval later.

For manual installation, the release asset `xparkle-rvlevel-0.5.0.zip` contains `custom_components/xparkle_rvlevel/`. Compare `SHA256SUMS`, preserve old source and copy only that folder. Never upload the source archive into HA as an integration.

### Recovering the previous installation

With cleanup confirmed and the entry disabled/unloaded, restore its saved exact previous component source, run the HA configuration check and restart normally while still disabled. The eight native options remain compatible, including fractional cadence. Verify options before re-enabling the same entry. If a newly created optional card resource/view was changed, restore only its saved unchanged object and reload the browser. No HA storage edits, full-instance restore or entry recreation is needed. Recorder/history preservation is a native update process contract; synthetic lifecycle tests are not a Recorder database test.

## Standard Home Assistant appearance

The integration creates **entities**, not a dashboard or a global theme. Start with [examples/levelling-card.yaml](examples/levelling-card.yaml): built-in Tile and Entities cards only, with no custom JavaScript, fixed background colors or theme overrides. Replace the example IDs with your actual registry IDs. Use these entities in any dashboard/layout/theme you prefer.

For optional front/rear/top caravan graphics, add `/xparkle_rvlevel/xparkle-card.js` as a JavaScript module resource, then use [examples/interactive-card.yaml](examples/interactive-card.yaml). The optional card follows HA theme variables by default (`appearance: native`). It remains a custom visualization, separate from the native-only default example. The stable exact-file URL is served with `Cache-Control: no-store`; after an integration update, reload each browser/Companion frontend to load the new class. Existing open tabs keep their already-loaded JavaScript until reload.

The quieter green design is an explicit per-card choice: `appearance: mint`, as in [examples/mint-card.yaml](examples/mint-card.yaml). It affects only that card. It is never installed as a global theme. Vehicle selection offers caravan, tandem caravan, motorhome and campervan; front/rear views always label physical sides in the direction of travel. Green levelling status is a separate semantic signal, shown only for fresh, valid, confirmed measurements within tolerance.

Old versioned 0.3 resource URLs should be replaced with the stable URL when upgrading. Keep the selected card appearance explicitly (`mint` to preserve the earlier green design). No dashboard/resource is silently rewritten at startup.

The optional graphic card colors correction arrows **blue for raise** and **orange for lower**, with arrow symbols and a text key. Its two illustrative spirit levels use fixed physical endpoints: **Vasen–Oikea** (left–right in the direction of travel) and **Perä–Keula** (rear–front). The bubble moves toward the **high end**; the correction arrow tells you which end to raise or lower. The displays share one fresh coherent sample. Each axis turns green within the configured height tolerance; the overall status requires both axes. Missing or stale data hides the bubbles. Bubble travel is illustrative, saturates at a one-percent slope, and has no calibrated degree scale.

## Measurement and battery

Turn **Measurement** on to make one owned connect dispatch. Reads are serialized, with a target start-to-start cadence of 0.5 seconds by default, configurable from 0.1–10 seconds. Slow reads extend cadence without queued catch-up. The most useful interval depends on the installation; faster host reads do not establish faster internal sensor sampling.

Turn Measurement off for controlled closure. A manual session expires after **10 minutes** unless the user presses **Keep measuring** while that session is active. Reading data, opening a dashboard and background HA events never renew it. No automatic reconnect is scheduled. Native backends may retry low-level establishment within the bounded connection dispatch.

**Battery refresh interval:** default 24 hours, integer 1–168 hours, or 0 to disable. One due attempt reads FFF2 at most once and closes. Busy/uncertain ticks are skipped without queuing. The cached percentage retains its original reception timestamp. Startup/reload/options changes do not force a read; the first scheduled attempt is a full configured interval later.

Connect budget is 20 seconds and each read budget is 5 seconds. Stop settles current owned work before disconnect. Normal cleanup uses 5-second settling and 10-second disconnect budgets, with bounded late-completion reconciliation. An unacknowledged cleanup blocks successors, including after native removal/re-addition; an off switch alone does not prove closure. Abrupt host power loss cannot guarantee graceful teardown.

## Geometry and interpretation

Set calculation reference spans along the rigid body in centimetres: width 1–500 and length 1–2000; 0 means unset. Overall body length, wheel track and axle-to-jockey-wheel distance are different spans. Height is not required. Estimates use `span × sin(angle)`, and values above 45 degrees are unsupported. Display precision is not measured sensor accuracy.

Mount location is front/rear/right/left in the direction of travel. It records location and moves the marker; it does not modify the device's stored orientation or rotate already-corrected output. Named corrections require explicit confirmation of the CURRENT output: uphill flag on means front high, left-tilt flag on means left low. A mount change clears that confirmation. Do not guess it from physical side alone.

Positive correction means raise that reference point while holding its opposite fixed. Opposite-end corrections are alternatives; applying both full amounts doubles the requested correction. Corner figures are advisory reference geometry, not measured jack travel or instructions to lift with corner steadies. Tolerance defaults to 0.25 cm (2.5 mm), configurable 0.05–5 cm. Both raw absolute reference differences must meet it. Stopped, stale, missing or unconfirmed data never show green. Calibration confirmation remains disabled because its command/effect has not been verified; no calibration command or software zero is implemented.

## Bluetooth compatibility

HA chooses the connection adapter automatically; this integration adds no scanner, direct proxy client or adapter setting. Configure sources under **Settings → Devices & services → Bluetooth**, and ESPHome proxies under their ESPHome entries. Every selectable route must match the reviewed backend/runtime set, have coherent capacity information and no pending native attempt/allocated target; otherwise the integration fails closed.

| Route | Required runtime |
|---|---|
| All routes | HA **2026.11.0**, habluetooth **7.1.2** |
| ESPHome proxy | bleak-esphome **4.0.0**, aioesphomeapi **46.25.0**, Bleak **3.0.2 or 3.1.0** |
| Local Linux BlueZ USB/UART | Bleak **3.0.2** |

`homeassistant` in hacs.json is only a minimum install version; it cannot express this exact runtime matrix. Newer HA/dependency versions are deliberately rejected until reviewed. One installed ESPHome device path has finite live-read evidence. Local BlueZ has source/synthetic evidence, not hardware acceptance. Other remote backends, Windows/macOS and broader device models are not claimed supported. Older proxies with incomplete allocation reports are rejected without changing firmware.

## Security and diagnostics

No pairing, device write, authentication command, notification subscription, calibration/reset/firmware operation, cloud telemetry or integration-owned HTTP client is implemented. Address/name/service matching is not cryptographic authentication; nearby spoofing can supply false data. Use the values as advisory information, not unattended actuation inputs. HA permissions control Start/Renew; the inactivity timeout is a usage rule rather than an abuse rate limit.

Own diagnostics omit device/source identifiers and raw errors. Native HA/Bluetooth logs can contain identifiers: sanitize them before sharing. See [SECURITY.md](SECURITY.md) and [NOTICE.md](NOTICE.md).

An authenticated administrator can explicitly call `xparkle_rvlevel.test_update_speed` with only `entry_id` and request a response. It is not automatic: one fixed read-only plan targets 1/.5/.25/.1 seconds, up to 8 reads each/32 total, 40-second acquisition deadline including connect, then bounded cleanup. Stop can end it; a lost HTTP response must be inspected in diagnostics before any new attempt. It measures host GATT timing, not physical or sensor-internal latency.

## Development

Python 3.14; pinned inputs are in `ci/requirements-test.txt` and `ci/constraints.txt`. These are version constraints, not wheel-hash locks. PR validation has read-only permissions and no secrets. Tests use fake radio with real HA lifecycle/forms/store/HTTP boundaries; they do not perform hardware tests. Run:

```sh
python -m pip install -r ci/requirements-test.txt -c ci/constraints.txt
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p pytest_asyncio.plugin -p no:cacheprovider tests
python script/build_frontend.py
python script/verify_release.py
```

Primary APIs: [HA Bluetooth](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/bluetooth/api.py), [HA lifecycle](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/config_entries.py), [habluetooth](https://github.com/Bluetooth-Devices/habluetooth/blob/v7.1.2/src/habluetooth/wrappers.py), [ESPHome BLE client](https://github.com/Bluetooth-Devices/bleak-esphome/blob/v4.0.0/src/bleak_esphome/backend/client.py), [Marketplace release guide](https://contributors.home-assistant.io/marketplace/guides/releases/).
