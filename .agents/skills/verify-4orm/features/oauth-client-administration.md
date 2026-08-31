# OAuth client administration

## Sub-features

Dashboard summary and handoff to the dedicated OAuth admin workspace; the central
scope inventory, including configured, zero-use, and observed-only scopes;
managed clients with complete issued-token activity grouped by principal;
newest-first, independently paginated dynamic registrations; protocol
capabilities; allowed resource audiences; token lifecycle counts; recent audit
activity; one-time secret generation; overlapping secret rotation; token
revocation; and client enablement.

## How to get to it (user POV)

Sign in as an administrator, open `admin`, expand the OAuth administration panel,
and follow `open OAuth administration` to `/admin/oauth`.

## Driving it with Playwright

Use the isolated seeded administrator. Confirm `/admin` shows aggregate OAuth
counts without rendering individual dynamic clients and that its visible link
opens `/admin/oauth`. Seed more than one dynamic-client page; confirm the first
page has 25 newest registrations, the older link reaches the remainder, and
scope inventory rows show aggregate dynamic/declarative counts instead of client
lists. Confirm defined scopes remain visible at zero use and an observed-only
historical scope is flagged. On the older page, inspect the dynamic Artbin MCP
client and confirm its grant and response types, token authentication, lifetime,
redirects, scopes, resource, and active/expired token counts. Expand a managed
client's issued token grants and confirm they identify the issuing human or
service principal, granted scopes, aggregate mint count, active count, and last
mint time without displaying a raw token. Confirm a seeded failed audit event
shows its client, actor, outcome, and safe detail. Generate the
`worldview-service` client's first secret through the visible button and check
that the one-time secret notice appears without horizontal overflow. Capture the
dedicated page at desktop and mobile widths.

## Gotchas

Declarative client sync creates client rows on startup. The generated secret is
stored only as a hash, so refreshing the page must replace the secret value with
rotation controls.
