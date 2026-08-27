# Homepage and navigation

## Sub-features

Profile cards, recent forum activity, the chat callout, global navigation, site banner, and responsive wrapping.

## How to get to it (user POV)

Open `/`. Use the top navigation to visit the forum, chat, personal page, settings, and authentication routes.

## Driving it with Playwright

Load the homepage at desktop and mobile widths. Capture the full page, assert that the chat callout is horizontally centered, and check that top-bar items remain visible without horizontal overflow. When recent posts or banners are involved, seed the matching state before server launch.

## Gotchas

The chat callout intentionally receives a changing inline visual style every five minutes. Verify its position and usability, not a fixed color, font, or border.
