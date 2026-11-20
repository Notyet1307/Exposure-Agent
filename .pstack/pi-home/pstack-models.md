# pstack model configuration

This project's sheet. In this repository it replaces the user's pstack-models.md; ignore that sheet's lines.

feature, refactoring: backup/deepseek-flash @max
bug-fix: backup/deepseek-flash @max
perf-issue: openai-codex/gpt-6.2-sol @high
hillclimb: backup/deepseek-flash @max
judgment and prose: openai-codex/gpt-6.2-astra @high
strongest judgment: openai-codex/gpt-6.2-astra @high
how explorer: backup/deepseek-flash @max
how explainer: openai-codex/gpt-6.2-sol @high
why investigators: backup/deepseek-flash @max
why synthesizer: openai-codex/gpt-6.2-sol @high
reflect tooling: backup/grok-4.7 @high
reflect judgment, divergent, synthesizer: openai-codex/gpt-6.2-sol @high
arena runners: backup/deepseek-flash @max, backup/grok-4.7 @high
arena cross-judge pool: backup/grok-4.7 @high, openai-codex/gpt-6.2-sol @high
swarm workers: backup/deepseek-flash @max
architect runners: openai-codex/gpt-6.2-sol @high, backup/deepseek-flash @max
interrogate reviewers: openai-codex/gpt-6.2-sol @high, backup/grok-4.7 @high
thermos reviewers: openai-codex/gpt-6.2-sol @high
no-comments reviewer: backup/grok-4.7 @high

default effort: high
session hook: on
pi ask tool: off
pi models: opus=openai-codex/gpt-6.2-sol, sonnet=backup/deepseek-flash, haiku=backup/grok-4.7

## Project constraints
- GPT models use the owner's openai-codex subscription only, never backup.
- When two strong Architect candidates are explicitly needed, use `openai-codex/gpt-6.2-sol @high, backup/grok-4.7 @high`.
- Real Claude (`fable`) and GLM challenger are currently unbound; disclose reduced panel diversity when running `interrogate` or when cross-family judge availability is constrained rather than halting the task.
- Use native pstack `agent` (not Cindy `subagent`); one writer per candidate worktree; fresh readonly reviewer context for substantive review, using a model distinct from the main session (`gpt-6.2-astra`) whenever available.
