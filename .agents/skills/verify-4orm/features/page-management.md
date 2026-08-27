# Page management

## Sub-features

Page listing, creation, editing, visibility, deletion, layout selection, and media snippet insertion.

## How to get to it (user POV)

Log in, open `settings`, expand `your pages`, and use the page title, `edit`, or `delete` controls. Expand `create page` to publish another page.

## Driving it with Playwright

Locate `#pages-section` and its list items. Verify the page link, visibility text, edit link, and delete button share a readable row at desktop width. Exercise mutations through their visible controls and wait for the resulting navigation or HTMX fragment before taking screenshots.

## Gotchas

Delete uses HTMX and a confirmation dialog. Register a dialog handler before clicking. Page content intentionally supports custom HTML and may change the appearance of the member page, so shared settings assertions should target application chrome rather than member content.
