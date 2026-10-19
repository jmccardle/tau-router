---
description: Split a goal across budgeted sub-agents (delegate), each with a model, slice and check
argument-hint: <goal>
---
Plan and carry out the goal below by delegating. Split it into parts a smaller model can finish, and call delegate once per part. Give each part a self-contained brief, the cheapest model you expect to do it well, a budget slice, and a shell check that exits 0 when the part is done. Parts that don't depend on each other can be delegated in the same response; they run in parallel. Use budget_status to see what you have. Each result tells you what was spent and what is left; re-delegate or fix up whatever failed. When everything is done, verify the whole goal yourself and summarize.

Goal:
$ARGUMENTS
