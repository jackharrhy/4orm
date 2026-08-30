# OAuth client administration

## Sub-features

Configured and dynamically registered OAuth client status, registration source,
allowed resource audiences, complete token usage grouped by principal, one-time
secret generation, overlapping secret rotation, token revocation, and client
enablement.

## How to get to it (user POV)

Sign in as an administrator, open `admin`, and expand the OAuth clients panel.

## Driving it with Playwright

Use the isolated seeded administrator. Confirm the configured
`worldview-service` client is visible, generate its first secret through the
visible button, and check that the one-time secret notice appears without
horizontal overflow. Expand token usage and confirm it identifies the issuing
human or service principal, granted scopes, aggregate mint count, active count,
and last mint time without displaying a raw token. Capture the panel at desktop
and mobile widths. Confirm declarative and dynamic clients are distinguished and
the dynamic Artbin MCP client's allowed resource is visible.

## Gotchas

Declarative client sync creates client rows on startup. The generated secret is
stored only as a hash, so refreshing the page must replace the secret value with
rotation controls.
