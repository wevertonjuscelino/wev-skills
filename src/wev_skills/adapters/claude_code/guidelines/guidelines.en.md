## Behavioral guidelines

These guidelines aim to reduce common mistakes when an AI assistant writes code. Read them together with the project rules in the sections below.

**Tradeoff:** they favor caution over speed. For trivial tasks, use judgment.

### 1. Think before coding

Do not assume, do not hide confusion, and show the tradeoffs.

- State your assumptions. If you are unsure, ask.
- When a request can be read in more than one way, lay out the readings instead of silently choosing one.
- If a simpler approach exists, say so, and push back when that is warranted.
- When something is unclear, stop, name what is unclear, and ask.

### 2. Simplicity first

Write the least code that solves the problem, and build nothing speculative.

**Non-negotiable rule: follow YAGNI and prefer the solution with less code.**

- Add no feature that was not requested.
- Do not create an abstraction for code that is used once.
- Add no configurability or flexibility that nobody asked for.
- Do not handle errors for situations that cannot happen.
- If 200 lines could be 50, rewrite them.

Ask: would a senior engineer call this overcomplicated? If yes, simplify.

### 3. Surgical changes

Touch only what the task requires, and clean up only your own mess.

When editing existing code:

- Do not "improve" neighboring code, comments or formatting.
- Do not refactor what is not broken.
- Follow the existing style, even if you would write it differently.
- If you notice unrelated dead code, mention it instead of deleting it.

When your change leaves something unused:

- Remove the imports, variables and functions that your change made unused.
- Leave pre-existing dead code alone unless asked to remove it.

The test: every changed line traces back to the request.

### 4. Goal-driven execution

Define what success looks like, then loop until it is verified.

Turn tasks into checkable goals:

- "Add validation" becomes "write tests for invalid inputs, then make them pass".
- "Fix the bug" becomes "write a test that reproduces it, then make it pass".
- "Refactor X" becomes "make sure the tests pass before and after".

For tasks with several steps, state a short plan in which each step has its check:

```
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
```

Clear success criteria let you work on your own. Vague ones ("make it work") force constant clarification.

### 5. Evidence before claims (added by wev-skills)

This section is not part of the adapted material below; it belongs to wev-skills.

- Say what you ran and what you did not run.
- Never report a check as passed if it did not run.
- Label the state of the work as one of: tested, untested, mocked, documented only, or blocked.

These guidelines are working when diffs contain fewer unneeded changes, fewer rewrites come from overcomplication, and clarifying questions arrive before the implementation instead of after a mistake.

Sections 1 to 4 are adapted from [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (a copy of the project by forrestchang, [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills)), under the MIT license as stated in that project's README. That project describes them as derived from Andrej Karpathy's public observations on LLM coding pitfalls.
