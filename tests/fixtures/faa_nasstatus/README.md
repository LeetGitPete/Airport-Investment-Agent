# FAA NAS Status fixtures

* `sample.xml` — a real, unedited capture of
  `https://nasstatus.faa.gov/api/airport-status-information` taken 2026-08-15 19:38 GMT.
  It contains a Ground Delay Program (SFO, low ceilings), a general departure delay (SFO,
  RWY:Construction) and eight airport-closure NOTAMs (PVD full curfew closure; LAX, HNL,
  PHL, LAS, ASE, SAN, CYS partial "closed to non-scheduled/GA" NOTAMs).
* `AirportStatus.dtd` — the FAA's own DTD for that feed
  (`https://nasstatus.faa.gov/AirportStatus.dtd`, v2.2), captured the same day. It is the
  authority for element names the live capture happened not to contain, notably
  `Ground_Stop_List (Program*)` / `Program (ARPT, Reason, End_Time)`.

Recapture with: `uv run python tests/fixtures/faa_nasstatus/make_fixture.py`.
