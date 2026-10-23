## Summary

<!-- What changes and why. -->

## What was tested

<!-- Commands you ran and their results. Paste real output; do not paraphrase. -->

```
make test
```

Result:

## Risk

<!-- What could go wrong, and for whom. Required when the risk is medium or high. -->

## How to revert

<!-- The exact steps or commit to undo this change. Required when the risk is medium or high. -->

## Review

<!-- Findings of the review rounds: what was fixed, and what was dismissed with its reason. `wev run report --format pr` prints this. -->

## Evidence for each claim

Label every claim in this PR with one of: implemented and tested, implemented but untested, simulated with mocks, documented only, blocked.

| Claim | Label | Evidence (test name, command or link) |
|---|---|---|
|  |  |  |

## Checklist

- [ ] Tests added, and they fail when the behavior breaks
- [ ] `make test` passes locally
- [ ] Both locales updated (`en` and `pt-BR` key sets are identical)
- [ ] Both documentation languages updated
- [ ] No new runtime dependency
- [ ] `docs/THIRD-PARTY.md` (and `NOTICE` if required) updated if third-party material was added
- [ ] No secrets, tokens or private data in the diff
- [ ] No empty directories or placeholder modules
