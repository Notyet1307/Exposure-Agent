# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Read on demand

- Read **`CONTEXT.md`** when the task needs domain terminology.
- Read only the **`docs/adr/`** entries that touch the current change.

If either location doesn't exist, **proceed silently**. Don't flag its absence or suggest creating it upfront. The `/domain-modeling` skill creates domain documentation lazily when terms or decisions actually get resolved.

## File structure

This repository uses a single-context layout:

```text
/
├── CONTEXT.md
├── docs/adr/
└── backend/app/domain/
```

## Use the glossary's vocabulary

When your output names a domain concept—in an issue title, refactor proposal, hypothesis, or test name—use the term defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the required concept isn't in the glossary yet, either reconsider whether you're introducing language the project doesn't use or note the gap for `/domain-modeling`.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001's accepted control-plane boundary—but worth reopening because…_
