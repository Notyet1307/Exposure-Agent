# Project workspace

## Sub-features
Create a project, find it again, open its detail, avoid duplicate creation on request replay, receive a default upload profile.

## How to get to it (user POV)
Sign in as an administrator, open the projects list and create a project. Default mode uses the public API; `--ui` also drives actual browser clicks. `--ledger` implies `--ui` and adds a second project plus the customer-ledger journey.

## Driving it with HTTP
Run the main helper with the project `.venv` interpreter. POST `/api/v1/login/access-token` authenticates the synthetic administrator. POST `/api/v1/projects/` with name `verification-pilot` and Idempotency-Key `pilot-create` must return 201; replay must return the same id. GET `/api/v1/projects/{id}` and the list must expose the same project; GET `/api/v1/projects/{id}/customer-upload-profile` must return version 1 and its actual `required_headers`. Read-only SQL verifies exactly one project row, and no artifact files are produced at this stage.

With `--ui`: fill Email and Password, click Log In; open `/?view=create`, fill Project name, click `Create and prepare inputs`. The project query parameter must match the created id. Reload, assert the visible project heading and same id, and record screenshots plus database count increasing from 1 to 2. Select the heading role, not matching text inside a hidden select option.

With `--ledger`: the same UI-created project then drives the real customer-ledger path. The project-only empty-artifact assertion still runs before upload. After the ledger upload, exactly one artifact must exist and its SHA-256 must equal the accepted upload `raw_sha256`; do not reuse the empty-directory assertion after a successful upload. The ledger journey is described in [customer-ledger](customer-ledger.md).

## Gotchas
Requires migrated empty synthetic PG and a seeded synthetic administrator. A 200 health response alone is insufficient. This verifies committed HEAD only, no authorization role matrix, project rename/archive or all concurrency cases. PostgreSQL17 is not production-version equivalence. Use the project `.venv/bin/python`; system python3 3.9.6 returns BLOCKED because it lacks the required tarfile filter. Run helper and UI from the same frozen verification copy when collecting evidence.
