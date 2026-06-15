# Agent Execution Guide

This repository is an agent-neutral Skill package. Follow these rules in Codex, Cursor, Gemini CLI, or any coding agent.

Treat it as a reusable skill, not as a one-off prompt or a standalone scraper. The script collects OPAC data; the references define the recommendation workflow, ranking rules, evidence rules, and report shape.

## Read Order

1. `README.md`
2. `SKILL.md` for concise operating rules
3. `references/workflow.md`
4. Task-specific references only as needed

## Tool Use

- Prefer `scripts/opac_survey.py` for OPAC collection when network access works.
- Use browser/computer automation only to verify UI behavior, inspect pages, or handle script failures.
- Use manual-assisted mode when the OPAC is inaccessible from the agent environment.
- Do not log into user accounts or perform account actions.

## Outputs

- Keep final reports aligned with `references/report-template.md`.
- Keep library holdings and external recommendations separate.
- Mark unverified, cached, external, and judgment-based claims explicitly.
- Include a "明天去图书馆该怎么借" action list.
