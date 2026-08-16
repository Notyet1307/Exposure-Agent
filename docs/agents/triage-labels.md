# Triage Labels

The delivery workflow uses five canonical triage roles. This file maps each role to the label string used by this repository.

| Canonical workflow role | Repository label | Meaning                                  |
| ----------------------- | ---------------- | ---------------------------------------- |
| `needs-triage`          | `needs-triage`    | Maintainer needs to evaluate this issue  |
| `needs-info`            | `needs-info`      | Waiting on reporter for more information |
| `ready-for-agent`       | `ready-for-agent` | Admission passed in the AGENT lane       |
| `ready-for-human`       | `ready-for-human` | Admission passed in the HUMAN lane       |
| `wontfix`               | `wontfix`         | Will not be actioned                     |

When a workflow rule or Skill names a canonical role, use the corresponding repository label from this table.

Edit the `Repository label` column to match the vocabulary already used by the repository.
