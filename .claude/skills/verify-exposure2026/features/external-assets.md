# External asset reading

## Sub-features
Read project-scoped external IP/domain/port asset versions and their structured details.

## How to get to it (user POV)
Open a project, enter external assets, select an existing version and open an asset detail.

## Driving it with HTTP
NOT_RUN: no external-source or model service is started by the pilot. Follow scripts/test-cloudatlas-fixture.sh and test-cloudatlas-structured.py only in a separately authorized isolated fixture setup. Future proof must capture the selected version, paged rows and detail, and verify persisted local reads while the fixture source is stopped. Do not invoke real cloud capabilities just to seed this map.

## Gotchas
Fresh project seed has no asset versions. An empty screen is not proof. Real source credentials, network calls and model invocation are excluded. Feature-map entries do not authorize external execution.
