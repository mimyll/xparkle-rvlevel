# Provenance and dependencies

This product contains original integration/session/test code and a source-derived protocol decoder. It contains no manufacturer APK, extracted manufacturer implementation or vendored third-party library. Protocol facts and public API behavior are documented in the README's primary-source references.

Home Assistant, habluetooth, Bleak, bleak-retry-connector, Bluetooth adapter/data libraries, bleak-esphome and aioesphomeapi are supplied by the host's existing HA environment and retain their respective licenses. They are not bundled in the component ZIP. The integration adds no Python requirements of its own and does not install, upgrade or replace those host dependencies.

Review dependency versions and advisories against the recorded runtime baseline before installation. Package metadata and advisory lookups are evidence of the reviewed versions, not a host-wide security audit or a guarantee of compatibility with future versions.

Public protocol reference: moggleif/libell, MIT-licensed source at commit
07bb51a84628b7736c0de88057342b8b214ae17a,
https://github.com/moggleif/libell/blob/07bb51a84628b7736c0de88057342b8b214ae17a/src/sensor/xparkleProtocol.ts.
This package contains an independently written decoder, not a copy of that
implementation or any manufacturer application code. Wire encoding resolution
(0.01 degree) is not demonstrated physical accuracy. Original artwork is unofficial.
