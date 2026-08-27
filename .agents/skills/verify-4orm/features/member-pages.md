# Member pages and layouts

## Sub-features

Profiles, public pages, default, simple, CSS-only, and raw layouts, custom CSS/HTML, profile cards, and export links.

## How to get to it (user POV)

Open `/u/<username>` and follow a page link, or choose `my page` after login.

## Driving it with Playwright

Verify each affected layout directly. For default and simple layouts, distinguish shared 4orm chrome from member-authored content. For raw and CSS-only layouts, assert only the contract that layout promises. Capture screenshots when shared CSS changes could leak into personal pages.

## Gotchas

Custom HTML, CSS, and JavaScript are intentional. Use only isolated seeded content, and do not point automated verification at an untrusted shared instance.
