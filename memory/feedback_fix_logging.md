---
name: Fix logging workflow
description: Every fix or feature requires an ADR, a LEARNING_GUIDE section, and a journal entry
type: feedback
---

Every non-trivial fix or feature implemented in this project must be documented in three places:

1. `docs/decisions/ADR-NNN-*.md` — the architectural decision record
2. `docs/LEARNING_GUIDE.md` — a lesson extracted from the work (what was learned, not just what was done)
3. `docs/journals/YYYY-MM-DD-*.md` — a session journal with problem, solution, and takeaways

**Why:** This is a learning project. The user wants a record of decisions, reasoning, and lessons that can be reviewed independently of the code. Documentation is part of the definition of done.

**How to apply:** After implementing any fix or feature, immediately write all three documents before moving to the next task. Do not batch documentation at the end of a session.
