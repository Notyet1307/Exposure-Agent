# Delivery Gate

Implementation work moves through these states:

1. A delivery spec is created in needs-triage.
2. The spec assigns stable Scenario IDs, explicit entry/exit state or artifact handoffs, and Release signals.
3. Candidate implementation issues are created as native children in needs-triage.
4. The parent stores one current Scenario coverage matrix and walking-skeleton chain; every scenario has DIRECT coverage, every handoff has a producer or external source, and every ENABLER has a consumer and exit condition.
5. Native blocking edges and child order satisfy strict-frontier order.
6. /admit-ticket validates the persisted coverage and graph, then sends the exact bundle to ticket-readiness-reviewer in a fresh context.
7. A human confirms the reviewer outcome.
8. READY children receive ready-for-agent for lane AGENT or ready-for-human for lane HUMAN.
9. The delivery parent receives ready-for-agent last.

Verdict and execution lane are independent: a complete human-only ticket is READY/HUMAN, not NEEDS_INFO. SPLIT candidates remain needs-triage. NEEDS_INFO candidates move to needs-info after confirmation. Any material change after review requires another admission run.

Wayfinder maps and wayfinder:* decision tickets are planning artifacts. They never receive the executable ready-for-agent label and are never reused as delivery parents. Any source revision, coverage matrix, candidate body, child order, or blocker change requires another admission run.

The label strings used by this repository are defined in docs/agents/triage-labels.md. Tracker-specific relationship operations are defined in docs/agents/issue-tracker.md.
