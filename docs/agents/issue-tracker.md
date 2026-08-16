# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number> --comments` and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies** — the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only — the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me` — the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.

Wayfinder maps and their children never receive the executable ready-for-agent label.

## Delivery-map operations

Used by /to-spec, /to-tickets, and /admit-ticket. A delivery map is separate from every Wayfinder map.

- **Draft parent**: create the delivery spec with needs-triage and no ready-for-agent.
- **Candidate child**: create each implementation ticket with stable source Scenario IDs, coverage role, and needs-triage, then attach it as a native GitHub sub-issue of the delivery parent.
- **Coverage**: keep one `## Ticket coverage` section containing exactly one `<!-- pi-ticket-planning:delivery-graph:v2 -->` marker and its JSON fence. This normalized object is the current Scenario handoffs, source revision/base/Spec content hash, real child IDs and body hashes, roles, starting states, verifications, lanes, walking skeleton, and blocker graph; do not duplicate it as a prose matrix or receipt.
- **Graph check**: `gh issue view <parent> --json body --jq .body | node "$PI_TICKET_PLANNING_ROOT/scripts/check-delivery-graph.mjs" --input -`. PASS is mandatory before Admission and activation.
- **Blocking**: use the same native issue-dependency endpoint documented above. Add edges only after every candidate has an issue id.
- **Order**: arrange native children in a stable topological order of internal blockers. For every `blocker -> dependent` edge, the blocker must be earlier in the native list. HerdrHarness Lite treats the first open child as the strict frontier and never jumps over it. GitHub can reprioritize a child with `gh api --method PATCH repos/<owner>/<repo>/issues/<parent>/sub_issues/priority -F sub_issue_id=<child-db-id> -F after_id=<previous-child-db-id>`; re-fetch after every completed reorder rather than trusting local intent.
- **Order check**: before admission and again before activation, run `node "$PI_TICKET_PLANNING_ROOT/scripts/check-frontier-order.mjs" --repo <owner>/<repo> --parent <number>`. PASS is mandatory; FAIL or an API/read error leaves the map in needs-triage.
- **Admission**: /admit-ticket validates Scenario coverage, state/artifact handoffs, walking skeleton, exact parent, children, order, and blockers before label mutation.
- **Activation**: add ready-for-agent to admitted AGENT children and ready-for-human to admitted HUMAN children, then add ready-for-agent to the delivery parent last. Remove needs-triage and needs-info from each activated issue.
- **Drift**: when a reviewed body, source, child order, or dependency changes, remove or withhold both ready labels and run admission again.
