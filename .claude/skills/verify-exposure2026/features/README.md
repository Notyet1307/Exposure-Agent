# User-facing feature map

- [Project workspace](projects.md): implemented synthetic API journey, plus real-browser project creation with `--ui`. See the fresh result.json for outcome.
- [Customer ledger](customer-ledger.md): implemented real-browser first-selection pilot with invalid uploads, preview, explicit apply, sidebar ledger read, reload, and independent API/SQL/artifact readback with `--ledger`. Full replacement, 409/recovery, manual revisions, reports and large-ledger capacity are NOT_RUN.
- [External asset reading](external-assets.md): mapped only, NOT_RUN by this pilot.

One passing journey is not full feature coverage. UI interactions, real integrations, production data and PostgreSQL18 equivalence require separate evidence. Maintain map and helper together when routes or preconditions change. Use the project `.venv/bin/python`; system python3 3.9.6 is blocked before source extraction.
