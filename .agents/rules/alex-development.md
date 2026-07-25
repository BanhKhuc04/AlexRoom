# ALEX Autonomous Development Rules

Before beginning any task, read:

@../../docs/ALEX_CURRENT_PROJECT_STATUS_REPORT_2026-07-26.md

## Scope

- Work on exactly ONE checkpoint at a time.
- Follow the NEXT ACTION PLAN from the current project status report.
- Inspect relevant source, tests, documentation, git history and runtime evidence before modifying production code.
- Do not expand the scope merely because adjacent problems are discovered.

## Evidence before code

Do not modify production code until there is trace, evidence, reproduction, failing test, or other concrete justification for the change.

Never fabricate evidence or success.

## Validation gates

Always distinguish these independently:

1. SOFTWARE PASS
2. RUNTIME PASS
3. PHYSICAL PASS

SOFTWARE PASS does not imply RUNTIME PASS.
RUNTIME PASS does not imply PHYSICAL PASS.

Never claim PHYSICAL PASS without real physical hardware evidence.

## Architectural safety

- Preserve existing ALEX architectural boundaries.
- Do not silently repair architectural debt outside the assigned checkpoint.
- Record architectural inconsistencies as architectural debt/correction for the proper future checkpoint.
- Avoid broad refactors unless the assigned checkpoint explicitly requires them.
- Existing stable functionality must not be broken to fix unrelated debt.

## Autonomous permissions boundary

Allowed:
- inspect repository
- edit files inside the assigned worktree
- add or update tests
- run local tests
- run lint/build commands
- inspect git diff/status/log
- create checkpoint reports

Not autonomous:
- production deployment
- physical hardware control
- production MQTT actions
- force push
- destructive repository operations
- release creation
- merging protected branches
- claiming hardware validation without evidence

Escalate to the human owner when one of these is required.

## Completion report

Every completed checkpoint must state:

- checkpoint objective
- evidence collected before modification
- files changed
- tests executed
- exact test results
- regressions checked
- remaining risks
- architectural debt discovered
- SOFTWARE PASS status
- RUNTIME PASS status
- PHYSICAL PASS status
- recommended next checkpoint

A checkpoint is BLOCKED when required evidence cannot be obtained.
