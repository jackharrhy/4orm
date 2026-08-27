# Authentication and settings

## Sub-features

Login, registration by invite, trust agreement, profile editing, appearance controls, widgets, notifications, and media navigation.

## How to get to it (user POV)

Choose `login` in the top bar, submit the login form, then choose `settings` after authentication.

## Driving it with Playwright

Use visible labels to fill the login form. Confirm authenticated navigation appears and `/settings` loads. At desktop and mobile widths, inspect headings, disclosure sections, forms, status areas, and controls for overflow or unexpected wrapping.

## Gotchas

The runner's seeded member has already accepted the trust agreement. Add a separate member when verifying that first-login flow. CodeMirror is loaded only on editor-heavy settings pages and may produce additional network activity before the page settles.
