# Core C+A comparison

This index maps the V2 core comparison and its optional NetFlow supplement. It does not add behavior or claim a real-browser pass.

## Authority

- Behavior and acceptance: [`docs/specs/product-logic-convergence-v2.md`](../../../../docs/specs/product-logic-convergence-v2.md) at `b603b45c853de764e47f99ccd1ed3ba98dec7c7e`.
- First-screen two-class difference summary & direct drill-down: [`docs/specs/comparison-result-first-screen-v1.md`](../../../../docs/specs/comparison-result-first-screen-v1.md) (PR #332 / Issue #331, `f4afbe8c6f444c7147ec334fa6fbb7e2fd9de2c0`).
- Same-version decision: [`docs/adr/0024-core-comparison-and-optional-netflow-evidence.md`](../../../../docs/adr/0024-core-comparison-and-optional-netflow-evidence.md).
- The local Spec bytes equal that commit. `git diff b603b45c853de764e47f99ccd1ed3ba98dec7c7e -- docs/specs/product-logic-convergence-v2.md` is empty.
- Task status and authorization stay in GitHub Issues (#292, #331).

## User journey

1. Open Comparison results for a project. The server resolves the latest regular, published, readable V2 result. The page fixes the result ID before it reads the summary, addresses, or materials.
2. If the applied customer register and the published CloudAtlas version are ready, generate the result from the confirmed same-space selection.
3. Read the first-screen two-class difference conclusion (`cloud_only` and `customer_only` counts, readable without scrolling or expanding at 1280×844 and 390×844; genuine zero only on complete coverage, explicit unknown pair on incomplete coverage), the three core counts, and the address list. Click either difference direction to drill directly into page 1 of that fixed class (clearing conflicting IP filters while preserving result ID and supplement binding), or filter, sort, page, open fixed address evidence, and return to the same result, filter, and page.
4. If a newer current result exists, the fixed page keeps the current result and offers an explicit newer-result action. It does not resolve latest again.
5. Optional NetFlow evidence attaches as a separate binding with an explicit valid-until cutoff. It never changes the core counts or classification.
6. Expiry, revocation, or loss of the supplement clears the supplement content. The readable C/A core stays readable. A core source refusal denies the fixed core result.

## Existing tests (not run evidence)

The table records test paths that exist in the current tree. It is not a run record for this candidate. Only the explicit NOT_RUN notes and the verification log in the task evidence directory describe this round.

| Behavior | Acceptance | Evidence | Boundary |
| --- | --- | --- | --- |
| Generate C+A without NetFlow, counts 3/1/1/1, stable pages and fixed pins | AC-01, AC-02, AC-13 | `backend/tests/api/routes/test_core_comparisons.py::test_two_source_core_http_is_fixed_and_has_no_netflow` | Real PostgreSQL HTTP |
| A lost create reply recovers the same idempotent result | AC-09 | `frontend/tests/product-logic.spec.ts`, `real C+A result stays fixed across browsing, optional evidence and expiry`; `backend/tests/api/routes/test_core_comparisons.py::test_concurrent_compare_create_uses_cas_and_same_key_recovery` | Real browser with real API and PostgreSQL; backend concurrency |
| Failed or newer attempts do not replace the regular current result | AC-04, AC-05 | `backend/tests/api/routes/test_core_comparisons.py::test_failed_attempt_history_does_not_replace_regular_current` | Real PostgreSQL HTTP |
| Update state keeps the saved result unchanged and rejects stale input | AC-08, AC-09 | `backend/tests/api/routes/test_core_comparisons.py::test_current_input_update_permissions_integrity_and_unsafe_downgrade`; `frontend/tests/core-reading.component.spec.ts`, `classification, core page, filter, sort and result changes reset both source pages` | Real PostgreSQL HTTP; route mock for the UPDATED prompt |
| Fixed result reading, filters, paging, materials, and return context | AC-10, AC-13, AC-14 | `frontend/tests/core-reading.component.spec.ts` (33 tests); the real C+A test in `frontend/tests/product-logic.spec.ts` | Route mock; real browser |
| An explicit core refusal removes content, and late or expired responses do not revive it | AC-10 | `frontend/tests/core-reading.component.spec.ts`, `an explicit core refusal removes the reading entries instead of retaining content`, `expiry while the drawer is open clears fixed contents and closes the drawer`, `a late old evidence page response cannot replace the selected source page`, `a late old evidence address response cannot replace the newly opened address` | Route mock |
| Supplement expiry and context revocation leave the core intact, and the legacy V1 result stays closed | AC-03, AC-11 | `backend/tests/api/routes/test_core_comparisons.py::test_supplement_expiry_and_context_revocation_do_not_change_core`; `frontend/tests/core-reading.component.spec.ts`, `first supplement ${fault} keeps core readable and offers explicit retry` (500, 403, timeout); `frontend/tests/product-logic.spec.ts`, `real evidence revocation rejects a delayed response without clearing C+A` | Real PostgreSQL HTTP; route mock; real browser |
| Empty versus partial core coverage | AC-01 | `backend/tests/api/routes/test_core_comparisons.py::test_core_distinguishes_empty_and_partial_coverage` | Real PostgreSQL HTTP |
| Viewer permission, archive, and unsafe downgrade | AC-18, AC-20 | `backend/tests/api/routes/test_core_comparisons.py::test_current_input_update_permissions_integrity_and_unsafe_downgrade` | Real PostgreSQL HTTP |
| The fixed result survives primary navigation and browser Back | AC-14 | `frontend/tests/netflow-correlation.component.spec.ts`, `primary navigation preserves a pinned current result and its reading position`, `primary navigation leaves legacy comparison while browser back keeps its fixed revision` | Route mock |
| Real IP and port material with supplement fault retry | AC-03, AC-14, AC-17 | `frontend/tests/core-reading.spec.ts` | Real browser and fixture; supplement failures are injected with `page.route` |
| First-screen two-class difference summary, zero-vs-unknown coverage contract, and direct drill-down to page 1 | First-screen AC1–AC4 | `frontend/tests/core-reading.component.spec.ts` (`first screen states both directions without scrolling or expanding at desktop and mobile`, `each direction opens its fixed class from page one, clears the IP filter and keeps result, binding and reads`, `the count contract keeps a genuine zero numeric and makes incomplete coverage one unknown pair`); `frontend/tests/product-logic.spec.ts` (`real fixed C+A first screen states both directions and opens each class from page one`) | Route mock; real browser with real API and PostgreSQL |

## Real journey preconditions

`frontend/tests/product-logic.spec.ts` needs `PRODUCT_LOGIC_FIXTURE`, `PRODUCT_LOGIC_EVIDENCE`, `TEST_API_URL`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, a real backend, and a private `product_browser_*` PostgreSQL database. `frontend/playwright.product.config.ts` selects that file and declares no `webServer`. The seed script `scripts/seed-product-logic-acceptance.py` runs the `core` and `netflow` stages with `uv run` from `backend`.

`frontend/tests/core-reading.spec.ts` needs `V2_READING_FIXTURE` and `V2_READING_EVIDENCE` plus the same real backend and browser runtime.

In a fresh worktree, run `bash scripts/wt-bootstrap.sh` to sync the root `.venv`. For quick inner-loop live UI inspection (viewport switching, ARIA snapshot, screenshots, console/network checks), use `node scripts/control-exposure.mjs` (built on `scripts/web-control.mjs`). Full real-browser execution of `product-logic.spec.ts` / `core-reading.spec.ts` remains NOT_RUN unless the `PRODUCT_LOGIC_*` / `V2_READING_*` fixtures, backend runtime, and evidence directory are explicitly provisioned; a skipped file is not a pass.

## Not this index

- NetFlow bulk progress ([`netflow-progress.md`](netflow-progress.md), `NetflowProgress`, `useNetflowProgress`) reports one bulk job's phases, file counts, heartbeat, and cancellation. It is not the optional supplement binding, core counts, observations, peers, evidence, or review.
- NetFlow observations, peers, evidence, and review are separate readers. `frontend/tests/netflow-results.component.spec.ts` and the legacy matrix in `frontend/tests/netflow-correlation.component.spec.ts` cover those surfaces. They do not prove the V2 supplement or core classification.
- External asset reading ([`external-assets.md`](external-assets.md)) remains NOT_RUN by this map.
- The fixed Spec's 18 CloudAtlas classes, model interpretation, reports, and deployment acceptance are not claimed here.

## Gaps

- No frontend test clicks the `Update comparison` action. The backend update semantics and the UPDATED prompt are mapped above; the action itself is NOT_RUN.
- Real browser execution for this candidate is NOT_RUN because the fixture, backend runtime, and evidence variables are absent.
- AC-12 IP, IPv6, and mapped identity, AC-18 cross-actor and source switch, and AC-19 viewport, language, theme, and keyboard behavior are only partly mapped by the route-mock matrix. Route mocks prove frontend rendering and request behavior, not the real backend or database.
