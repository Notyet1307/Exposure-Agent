# Core C+A comparison

This index maps the V2 core comparison and its optional NetFlow supplement. It does not add behavior or claim a real-browser pass.

## Authority

- Behavior and acceptance: [`docs/specs/product-logic-convergence-v2.md`](../../../../docs/specs/product-logic-convergence-v2.md) at `b603b45c853de764e47f99ccd1ed3ba98dec7c7e`.
- Same-version decision: [`docs/adr/0024-core-comparison-and-optional-netflow-evidence.md`](../../../../docs/adr/0024-core-comparison-and-optional-netflow-evidence.md).
- The local Spec bytes equal that commit. `git diff b603b45c853de764e47f99ccd1ed3ba98dec7c7e -- docs/specs/product-logic-convergence-v2.md` is empty.
- Task status and authorization stay in GitHub Issue #292.

## User journey

1. Open Comparison results for a project. The server resolves the latest regular, published, readable V2 result. The page fixes the result ID before it reads the summary, addresses, or materials.
2. If the applied customer register and the published CloudAtlas version are ready, generate the result from the confirmed same-space selection.
3. Read the three core counts and the address list. Filter, sort, page, open fixed address evidence, and return to the same result, filter, and page.
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

## Real journey preconditions

`frontend/tests/product-logic.spec.ts` needs `PRODUCT_LOGIC_FIXTURE`, `PRODUCT_LOGIC_EVIDENCE`, `TEST_API_URL`, `FIRST_SUPERUSER`, `FIRST_SUPERUSER_PASSWORD`, a real backend, and a private `product_browser_*` PostgreSQL database. `frontend/playwright.product.config.ts` selects that file and declares no `webServer`. The seed script `scripts/seed-product-logic-acceptance.py` runs the `core` and `netflow` stages with `uv run` from `backend`.

`frontend/tests/core-reading.spec.ts` needs `V2_READING_FIXTURE` and `V2_READING_EVIDENCE` plus the same real backend and browser runtime.

In the 2026-11-16 repair worktree, `backend/.venv` and the root `.venv` are absent and the `PRODUCT_LOGIC_*` and `V2_READING_*` variables are unset. The real journeys are NOT_RUN for this candidate. A skipped file is not a pass.

## Not this index

- NetFlow bulk progress ([`netflow-progress.md`](netflow-progress.md), `NetflowProgress`, `useNetflowProgress`) reports one bulk job's phases, file counts, heartbeat, and cancellation. It is not the optional supplement binding, core counts, observations, peers, evidence, or review.
- NetFlow observations, peers, evidence, and review are separate readers. `frontend/tests/netflow-results.component.spec.ts` and the legacy matrix in `frontend/tests/netflow-correlation.component.spec.ts` cover those surfaces. They do not prove the V2 supplement or core classification.
- External asset reading ([`external-assets.md`](external-assets.md)) remains NOT_RUN by this map.
- The fixed Spec's 18 CloudAtlas classes, model interpretation, reports, and deployment acceptance are not claimed here.

## Gaps

- No frontend test clicks the `Update comparison` action. The backend update semantics and the UPDATED prompt are mapped above; the action itself is NOT_RUN.
- Real browser execution for this candidate is NOT_RUN because the fixture, backend runtime, and evidence variables are absent.
- AC-12 IP, IPv6, and mapped identity, AC-18 cross-actor and source switch, and AC-19 viewport, language, theme, and keyboard behavior are only partly mapped by the route-mock matrix. Route mocks prove frontend rendering and request behavior, not the real backend or database.
