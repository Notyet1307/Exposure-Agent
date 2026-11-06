# Issue tracker: GitHub

GitHub Issues are the repository's only task-status, dependency, and authorization surface. They must cite the approved Git Spec path and commit. `AGENTS.md` defines the execution and publication lifecycle: Codync dispatches work, Claude Code runs the implementation with pstack methods, and the project owner holds goal, design, route, and acceptance. Behavior authority is the pinned Spec, not this tracker.

## Scope and reads

- The GitHub Issue confirmed in the current conversation authorizes work and records status. Read the Spec it cites for behavior and acceptance criteria.
- Issue operational detail must not silently change Spec meaning. Change the approved Spec first, record replacement, then re-check affected tasks.
- Read live issues and pull requests through `gh` or another already authorized GitHub-native capability. A bare `#42` may identify either kind; resolve it before acting.
- Read the current issue, its open native dependencies, and the current PR state. Historical evidence and closed work are not default implementation context.

## Native relationships

- Use GitHub sub-issues for parent/child organization and GitHub issue dependencies for blocking relationships.
- Dependency API writes require the blocker's numeric database `id`, not its issue number or GraphQL `node_id`.
- Re-read live dependency state after relationship mutations; only open blockers prevent work.
- Labels are routing metadata, not execution authorization. See `triage-labels.md`.

## Mutations and completion

- Use `gh` or another already authorized GitHub-native capability for repository, search, PR, push, and CI operations.
- Keep implementation, verification, commit, push, PR, CI/review, merge, deployment when required, and Issue closure as separately authorized and verified lifecycle states. A finished pstack step does not authorize the next state.
- The project owner organizes independent, non-author Standards and Spec reviews against the pinned Spec before merge; the original implementer fixes blockers and the reviewers re-review. Independent business acceptance is separate from those code reviews. Record PASS / FAIL / BLOCKED / NOT_RUN; human risk-accept is a separate decision.
- Close the Issue only after its PR is merged and any required deployment acceptance is complete or explicitly not applicable.

There is no Controller, Admission, release-graph, or ready-label automatic authorization in the current workflow. Normal task dispatch by the project owner is not Controller or Admission. `/to-spec` and `/to-tickets` remain available as methods; `delivery-gate.md` is historical and is not a current entry.
