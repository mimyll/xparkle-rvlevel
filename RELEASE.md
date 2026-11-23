# 0.5.1

Fix connections being rejected after a Home Assistant patch update. New or untested HA Core versions no longer fail just because their version string differs from the recorded reference. ESPHome admission checks actual Bluetooth APIs, bound device identity, active registered sources, target ownership and free capacity. Package versions are diagnostic information, collected once off the event loop; this also fixes metadata filesystem warnings.

Failed admission reports only allowlisted reason codes. The conservative local BlueZ teardown-confirmation limitation remains explicit; unverified cleanup cannot be bypassed. No new device command, scanner, automatic reconnect or pairing is introduced.

All existing entities/options/cache/card appearances are retained. Before updating, stop measurements, confirm cleanup, disable and verify unload, retain exact old component source, update through Marketplace and restart while still disabled. Verify and enable the same entry. Do not remove/re-add it. Physical accuracy, sample age, movement latency and battery lifetime remain unverified. This repository is manually added only; no default catalog submission.
