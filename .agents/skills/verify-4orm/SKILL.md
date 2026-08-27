---
name: verify-4orm
description: Verify 4orm through isolated real-browser flows with desktop and mobile screenshots, browser logs, and layout assertions. Use after changing 4orm templates, shared CSS, navigation, authentication, settings, page management, or other user-visible behavior; use before declaring UI work complete.
---

# Verify 4orm

Drive the server-rendered application through the same forms, links, HTMX responses, and responsive layouts a member uses. Unit and route tests remain useful, but they do not replace browser evidence for visual changes.

Read the relevant file under `features/` before verifying a mapped feature. Update that map when a user-visible route or proof requirement changes.

## Launch

From the repository root, install the locked environment and Chromium once:

```bash
uv sync --group dev
uv run playwright install chromium
```

For an isolated verification run:

```bash
uv run python .agents/skills/verify-4orm/scripts/verify_4orm.py
```

The helper chooses an unused loopback port, creates and seeds a temporary SQLite database, starts 4orm with test-only environment values, waits for HTTP readiness, and removes only the runtime state and process it created. It never reads or writes `data/4orm.db`.

## Doctor

Run the helper first. It checks that the spawned server answers `/`, that the page identifies itself as 4orm, and that Chromium can render the application. If it fails before driving, inspect `server.log`, `console.json`, and `report.json` in the reported evidence directory.

## Drive

The default flow verifies:

1. The homepage at desktop width, including the centered chat link.
2. Login through the visible form using the isolated seeded member.
3. Settings and page-management controls, including edit/delete alignment.
4. Homepage and settings at mobile width.

Prefer Playwright roles, labels, visible text, and stable route paths. Use layout measurements only for genuinely visual requirements such as centering, wrapping, clipping, and overlap. Do not replace visible user actions with direct database mutations after launch.

For focused or new flows, read [features/README.md](features/README.md) and extend the runner when the assertion should remain part of 4orm's regression coverage.

## Evidence

Evidence is written beneath `artifacts/verification/4orm/<UTC timestamp>/` unless `--evidence <directory>` is provided:

- desktop and mobile screenshots capture the relevant visible states;
- `report.json` records each assertion and its measured values;
- `console.json` records browser warnings, errors, and page errors;
- `server.log` preserves application output.

Inspect the screenshots after every UI change. A file existing is not proof that its layout is correct. Treat unexpected browser errors, failed requests, overlap, clipping, or unexplained wrapping as failures.

## Cleanup

The helper closes Chromium, terminates the exact server process group it started, and deletes its temporary database and runtime directory. It preserves evidence. Never kill Uvicorn or Python processes by name.

## Helpers

`scripts/verify_4orm.py` is the isolated browser verification runner. Run it with `--help` for its arguments.
