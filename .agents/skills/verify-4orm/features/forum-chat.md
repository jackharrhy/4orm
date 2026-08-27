# Forum and chat

## Sub-features

Forum index, threads, replies, quotes, previews, moderation controls, chat history, presence, and message submission.

## How to get to it (user POV)

Choose `forum` or `chat` from the top navigation. Open a thread from the forum index to reach replies and thread controls.

## Driving it with Playwright

Seed users, threads, and posts before launch when needed. Exercise visible links and forms, capture the state before and after mutations, and verify HTMX or SSE updates settle without browser errors. Use mobile screenshots for action-heavy thread headers.

## Gotchas

Chat uses server-sent events, so `networkidle` is not a suitable readiness condition there. Wait for visible presence or message elements instead. Forum custom HTML is trusted content; keep verification fixtures controlled.
