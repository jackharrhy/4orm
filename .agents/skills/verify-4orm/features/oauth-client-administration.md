# OAuth client administration

## Sub-features

Configured OAuth client status, recent token principals and lifecycle, one-time
secret generation, overlapping secret rotation, token revocation, and client
enablement.

## How to get to it (user POV)

Sign in as an administrator, open `admin`, and expand the OAuth clients panel.

## Driving it with Playwright

Use the isolated seeded administrator. Confirm the configured
`worldview-service` client is visible, generate its first secret through the
visible button, and check that the one-time secret notice appears without
horizontal overflow. Expand recent token activity and confirm it identifies the
issuing human or service principal without displaying a raw token. Capture the
panel at desktop and mobile widths.

## Gotchas

Declarative client sync creates client rows on startup. The generated secret is
stored only as a hash, so refreshing the page must replace the secret value with
rotation controls.
