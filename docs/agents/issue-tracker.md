# Issue tracker: GitHub

GitHub Issues are the repository's task and specification source. The current OMP session uses GitHub-native issues, pull requests, sub-issues, and dependencies; `AGENTS.md` defines the execution and publication lifecycle.

## Scope and reads

- The GitHub Issue confirmed in the current conversation is the only implementation Spec / Acceptance Criteria.
- Read live issues and pull requests through the current OMP GitHub resources. A bare `#42` may identify either kind; resolve it before acting.
- Read the current issue, its open native dependencies, and the current PR state. Historical evidence and closed work are not default implementation context.

## Native relationships

- Use GitHub sub-issues for parent/child organization and GitHub issue dependencies for blocking relationships.
- Dependency API writes require the blocker's numeric database `id`, not its issue number or GraphQL `node_id`.
- Re-read live dependency state after relationship mutations; only open blockers prevent work.
- Labels are routing metadata, not execution authorization. See `triage-labels.md`.

## Mutations and completion

- Prefer the current OMP GitHub device for repository, search, PR, push, and CI operations. Use authenticated GitHub-native capability only when the device does not expose the required mutation.
- Keep implementation, verification, commit, push, PR, CI/review, merge, deployment when required, and Issue closure as separately verified lifecycle states.
- Run independent OMP Standards and Spec/AC reviews before merge; fix blockers and re-review.
- Close the Issue only after its PR is merged and any required deployment acceptance is complete or explicitly not applicable.

There is no Controller, Admission, release-graph, ready-label, or external planning handoff in the current workflow.
