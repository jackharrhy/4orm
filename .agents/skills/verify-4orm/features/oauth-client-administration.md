# OAuth client administration

## Sub-features

OAuth summary counts; the central scope inventory, including configured,
zero-use, and observed-only scopes; configured and dynamically registered client
status; protocol capabilities; allowed resource audiences; token lifecycle
counts; complete issued-token activity grouped by principal; recent audit
activity; one-time secret generation; overlapping secret rotation; token
revocation; and client enablement.

## How to get to it (user POV)

Sign in as an administrator, open `admin`, and expand the OAuth clients panel.

## Driving it with Playwright

Use the isolated seeded administrator. Confirm defined scopes remain visible at
zero use, configured scopes name their clients, and an observed-only historical
scope is flagged. Expand the dynamic Artbin MCP client and confirm its grant and
response types, token authentication, lifetime, redirects, scopes, resource,
registration source, and active/expired token counts. Expand issued token grants
and confirm they identify the issuing human or service principal, granted scopes,
aggregate mint count, active count, and last mint time without displaying a raw
token. Confirm a seeded failed audit event shows its client, actor, outcome, and
safe detail. Generate the `worldview-service` client's first secret through the
visible button and check that the one-time secret notice appears without
horizontal overflow. Capture the panel at desktop and mobile widths.

## Gotchas

Declarative client sync creates client rows on startup. The generated secret is
stored only as a hash, so refreshing the page must replace the secret value with
rotation controls.
