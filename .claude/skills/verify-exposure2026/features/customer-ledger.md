# Customer ledger

## Sub-features
Upload a customer XLSX, reject invalid structure or values, preview a first selection without changing the current pointer, explicitly set the current input, read the accepted ledger rows and fields, and refresh persisted values.

This pilot covers the first-selection path only: no current input, then one accepted upload becomes current. Selecting a replacement when a current input already exists, manual revisions, archiving, reports, and large ledgers are NOT_RUN.

## How to get to it (user POV)
Sign in as an administrator. Create a project through the project form and land on `/?project=<ID>&view=inputs`. In the `Upload XLSX` card choose a file with the `XLSX file` input, then press the form's `Upload` button. The server validates the workbook. An accepted file appears in `Accepted uploads` with status `Available`, but the project input is still `Not ready` and the upload is not current until the user explicitly applies it.

On the new file's row press `Preview selection`. A `Selection preview` card shows current and new record/IP counts plus added, removed and changed IP counts. Press `Set as current input`. The success status says the file is now the current input and history is unchanged. Press `Customer asset ledger` in the sidebar, not a remembered URL. The ledger shows the fixed current version, total active records, distinct IPs, matching source records, and a row per source record. Press `Details` on a row to read its fields. A page reload keeps the same ledger version and rows.

## Driving it with the helper
Use the skill's [Launch prepare/check block and Helpers run block](../SKILL.md) with `--ledger` to execute the frozen helper. `--ledger` implies `--ui`. The helper reads the API-created project's actual upload profile through GET `/api/v1/projects/{id}/customer-upload-profile` and builds the fixtures from its `required_headers`. If those headers differ from the expected five headers, fixture generation returns BLOCKED, not a silently adapted workbook. The UI script separately reads the UI-created project's profile and requires it to match before uploading; a mismatch there is a product-consistency FAIL, not a skipped journey.

The real browser path executes in this order:

1. Login form, create project, reload, confirm the project id and heading.
2. Upload `customer-ledger-missing-header.xlsx`, a small workbook missing `web界面url`. Assert 422, code `missing_required_structure`, field `web_url`, and the visible message `The workbook is missing required structure.` with a `Web URL` diagnostic.
3. Upload `customer-ledger-port-70000.xlsx`, a small workbook with start and end port 70000. Assert 422, code `invalid_required_value`, field `start_port`, reason `port_out_of_range`, limit 65535, and the visible message plus `Port must be between 1 and 65535`.
4. After each rejected upload, assert the upload list still has count 0 and `current_customer_upload_id` is null, and the ledger read still has no `upload_id` or `current_upload_id`.
5. Upload `customer-ledger-valid.xlsx` with two rows built from the actual required headers: `192.0.2.10` and `192.0.2.11`, ports 443, `否`, empty URL. Assert 201, record_count 2, profile_version 1, the accepted message, an `Available` row, and that the project input is still `Not ready`.
6. Assert the current pointer is still null after upload and no POST to `/customer-ledger/replacements` has happened.
7. Press `Preview selection`. Assert POST `/api/v1/projects/{id}/customer-ledger/replacements/preview` returns 200, `current_upload_id` is null, candidate record/IP counts are 2/2, added/removed/changed are 2/0/0, and `Selection preview` is visible.
8. Assert the current pointer is still null after preview and no apply request has happened.
9. Press `Set as current input`. Assert POST `/api/v1/projects/{id}/customer-ledger/replacements` returns 201 with the candidate id, `expected_upload_id` null, and the same project id. Assert the confirmation message and that the current pointer now equals the upload id.
10. Read the ledger through the public API. Assert upload id equals current upload id, revision id is null, count/total records/unique IPs are 2/2/2, both IPs are present, and each row has start port 443, end port 443, `is_web` `否`, and null `web_url`.
11. Press `Customer asset ledger` inside the sidebar. Assert the URL path `/projects/{id}/customer-ledger`, the heading, `2 matching source records`, `2 active records`, `2 distinct IPs`, and both rows with `443` and the web marker. Press `Details` on `192.0.2.10` and assert the field labels and values, including `Web URL` as `Not provided`.
12. Reload directly (pressing `Details` did not add a row filter) and assert the same two rows and `2 matching source records` persist.
13. Independently re-read GET `/api/v1/projects/{id}/customer-uploads`, GET `/api/v1/projects/{id}/customer-ledger`, read-only SQL for the project pointer/upload/artifact/replacement counts, and the persisted artifact file. Assert exactly one artifact exists, its SHA-256 equals the accepted upload `raw_sha256`, the SQL pointer equals the upload id, there is one replacement receipt, and there are zero manual revisions.

The UI uses the real replacements preview and apply endpoints. The old `POST /api/v1/projects/{id}/customer-uploads/{upload_id}/select` route is not the UI application path and must not be used to fake this journey. No response is mocked.

## Gotchas
Read the actual profile before generating a workbook. The default required headers are `资产IP`, `起始端口`, `结束端口`, `是否web界面`, `web界面url`; a different profile blocks the synthetic fixture rather than weakening validation.

Upload success is not application. After a successful upload the row is `Available`, the project input remains `Not ready`, and the current pointer is still null. The helper asserts both the API pointer and the absence of an apply request before the explicit click.

The artifact appears at upload acceptance, before the explicit selection. The project smoke's empty-artifact assertion applies only before upload. After a successful upload assert exactly one artifact and its SHA-256, not an empty directory. In this path the artifact row is linked through `customer_uploads.artifact_id`; `artifacts.project_id` is null. Read-only SQL must join through `customer_uploads`, not filter `artifacts.project_id`.

The first selection has no ledger revision. After apply, `current_revision_id` and `revision` are null and the ledger shows `Accepted input`. That is expected for this path, not a persistence failure.

Clicking a ledger row's IP adds a `ledger_ip` filter to the URL. `Details` only opens the record panel and does not filter. Clear the filter with `All IPs` before reloading if the proof needs all rows; otherwise the reload correctly shows only the filtered row.

For an apply response with a definitive rejection status of 400, 401, 403, 404, 409, or 422, the page calls `clearIntent`, removing the saved request identity and `pendingReplacement`. A 409 means the current version or profile changed and the request was rejected. Preview the latest version again. There is no pending intent or `Recover result` control after that rejection.

For an unknown apply outcome, such as a network error or 5xx response outside those definitive statuses, the page retains `pendingReplacement` and the saved request identity. It shows `Recover result`, which sends GET `/api/v1/projects/{id}/customer-ledger/replacements/{operation_key}`. A successful read confirms the receipt. Only a GET 404 while the project is writable enables `Resend original request`, using the original identity and request. Other read errors retain the identity so the user can retry the read.

409 rejection and re-preview, unknown-outcome receipt recovery, and GET-404 original-request resend remain NOT_RUN in this pilot. These branches are mapped from source, not verified in the browser. Full replacement when a current input already exists, manual revisions/archiving, reports, CloudAtlas or external sources, model calls, PostgreSQL18/Docker equivalence, and large-ledger capacity also remain NOT_RUN.
