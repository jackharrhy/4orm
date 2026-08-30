# OAuth authorization

Verify the member-facing consent screen after authentication. Open
`/oauth/authorize` with a configured public client, valid redirect URI, PKCE S256
challenge, and state.

For a resource-bound client, verify the consent screen displays the already
validated resource and scope while preserving both in hidden form controls.

At desktop and mobile widths, capture the consent screen and verify that approve
is presented as the primary action, deny is presented as the secondary action,
and neither action wraps or overflows. Measure the computed text-to-background
contrast for both buttons and the secondary button border-to-page contrast.
Require WCAG AA text contrast of at least 4.5:1 and a visible control boundary of
at least 3:1. Check the visible keyboard focus treatment as part of the desktop
flow.
