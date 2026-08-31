# Delivery Gate

Implementation work moves through one accepted Delivery Spec and one Case-bound Release Graph:

1. `/to-spec` publishes the Delivery Spec Parent with `needs-triage` and records its acceptance receipt.
2. The accepted Parent becomes immutable authority.
3. `/to-tickets` drafts complete candidate children, independently reviews their readiness and graph, then obtains exact human approval before any tracker write.
4. One atomic publication creates all candidates in `needs-triage`, attaches them as native children, persists native blocker edges and order, and binds the matching `delivery-release-graph:v3` to the Planning Case.
5. Publication drift or any partial tracker result fails closed; candidates remain non-executable until the graph is rebuilt from fresh tracker state.
6. The default next route is `/prepare-codex-release`, which prepares one exact Codex Controller handoff and obtains one human approval without applying ready labels.

A human may explicitly select the Legacy `/admit-ticket` branch instead. That branch performs its own independent admission review before any `ready-for-agent` or `ready-for-human` mutation. Legacy activation labels eligible children first and the Parent last.

Verdict and execution lane are independent: a complete human-only ticket is `READY/HUMAN`, not `NEEDS_INFO`. `SPLIT` candidates remain `needs-triage`; confirmed `NEEDS_INFO` candidates move to `needs-info`. Any material source, candidate, relationship, Oracle, ownership, or accepted-base change requires a new graph and review.

Wayfinder maps and `wayfinder:*` decision tickets are planning artifacts. They are never executable Delivery Parents and never receive ready labels.

Label strings are defined in `docs/agents/triage-labels.md`. Tracker relationship operations are defined in `docs/agents/issue-tracker.md`.
