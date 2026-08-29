# Design reference

## Sub-features

The public `/design` route, application palette, typography, controls, layout
specimens, responsive rules, and the styling boundary between shared 4orm UI
and member-authored pages.

## How to get to it (user POV)

Open `/design` directly. Authentication is not required.

## Driving it with Playwright

At desktop and mobile widths, confirm every section is visible and the colour
swatches, rule grid, controls, and boundary copy fit without horizontal
overflow. Check the primary and secondary control text contrast, focus the
primary control, and capture a full-page screenshot at each viewport.

## Gotchas

The page intentionally demonstrates 4orm's square, border-led application
style. Do not treat the absence of shadows, rounded cards, external fonts, or
motion as missing polish. All page-specific selectors must remain scoped below
`.fourm-shell` and use the `fourm-` prefix.
