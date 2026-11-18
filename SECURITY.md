# Security policy

## Supported candidate and runtime

Version 0.4.0 is the current public preview. The initial runtime support is Home Assistant 2026.11.0 / habluetooth 7.1.2. ESPHome uses bleak-esphome 4.0.0 / aioesphomeapi 46.25.0 and Bleak 3.0.2 or 3.1.0. Local Linux BlueZ requires Bleak 3.0.2. Runtime guards reject other combinations before a native connection is dispatched. This intentionally narrow baseline must be reviewed when dependencies change; do not bypass it to claim broader compatibility.

## Threat boundary

- Bluetooth advertisements and FFF2 data are untrusted. The protocol has no implemented cryptographic device authentication. Matching address, exact name and FFF0 correlate an intended candidate; a nearby impersonator can provide false angles or battery data. Physical calibration, mounting signs and sample age are unverified.
- Home Assistant is the trusted host. Its native entity permissions govern Start/Stop/Renew. An authorized controller can renew or start sessions repeatedly; the ten-minute rule is not an authorization boundary or abuse rate limit.
- The integration accepts only the fixed read protocol. It has no pairing, GATT write, authentication, notification, reset, firmware, arbitrary UUID/command or direct proxy API operation. No new scanner, external HTTP client or cloud telemetry is introduced. Exact-file routes (including a stable no-store URL) expose only public card code/artwork; no directory or private state is served. An authenticated-admin-only finite speed diagnostic accepts only a loaded entry ID and the fixed read plan. One native connect dispatch is bounded to 20 seconds; reviewed backends may internally retry establishment within that budget. Reported connection_attempts counts dispatches, not low-level radio attempts.
- One owner serializes manual and scheduled operations. Failed/cancelled connection cleanup cannot be inferred from a discarded local backend; uncertain cleanup blocks successors across native entry removal and re-addition as well as within a session. Removed-entry schedules/cache producers are detached, but unresolved target ownership is retained until confirmed safe. A normal acknowledged teardown must complete before another session is admitted. Abrupt HA/host failure cannot guarantee graceful radio teardown.
- A cached battery value retains its original receive timestamp. HA receipt time does not establish the sensor's internal sample time or accuracy. Do not use these values for unattended safety-critical actuation.

## Data and logs

Target address/name remain in HA's native config entry; stable registry IDs use the private configured address. The battery cache stores only a percentage and original UTC receive timestamp through native private atomic Store operations. No credentials are requested.

The component's diagnostics use an explicit allowlist. This does not sanitize HA-wide logs: HA, habluetooth or backend libraries may log names, addresses and connection paths. Remove identifiers and credentials before sharing diagnostics/logs. Never attach raw APKs, application data, HA configuration, tokens or private research to a public report.

## Reporting and release checks

Report vulnerabilities through GitHub private vulnerability reporting at https://github.com/mimyll/xparkle-rvlevel/security/advisories/new. If that channel is unavailable, contact the maintainer privately through an existing channel; do not post exploit details, device identifiers, tokens or raw logs in public issues.

Each candidate requires source review, targeted local tests, dependency-advisory evidence, a curated source allowlist and exact package/file hashes. An empty advisory result does not prove the absence of vulnerabilities. Review the final runtime and component-only recovery before installation. Remote CI, HACS validation and hardware acceptance must be reported separately from local checks.
