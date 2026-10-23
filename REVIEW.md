# Review guide for wev-skills

## What failure looks like

- A capability is claimed without evidence: a statement of what works, with no test, adapter or measurement behind it, or without one of the labels implemented and tested, implemented but untested, simulated with mocks, documented only, blocked.
- A user-facing string sits outside i18n, or the `en` and `pt-BR` locale files do not have identical keys.
- A document changes without its twin: every English document has a Brazilian Portuguese one, changed in the same commit.
- A rule exists only in Markdown: if a rule matters, code in the engine must enforce it and a test must fail when the code breaks.
- A security statement is stronger than `SECURITY.md`: the engine is a guardrail for a fallible agent, not a boundary against an adversarial one, so "prevents" or "guarantees" about a control that agent can undo is a defect.

## Skip

- agents/*.md
- evals/reports/*

## Nits

max: 3

Naming and formatting are for `make lint`; report a nit only when it would mislead a reader.

## Important

A defect in the guards, approvals, path confinement, redaction or verification code, a limit that rejects valid input, and a change that makes an unverified task look verified.
