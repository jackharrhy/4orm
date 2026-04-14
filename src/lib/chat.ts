/**
 * Chat page: unread counter in tab title + flash on new messages.
 * Also handles auto-scroll to bottom.
 */

let unreadCount = 0;
let flashInterval: ReturnType<typeof setInterval> | null = null;
let isFlashOn = false;
const baseTitle = "4orm · chat";

function updateTitle(): void {
  if (unreadCount > 0) {
    document.title = `(${unreadCount}) ${baseTitle}`;
  } else {
    document.title = baseTitle;
  }
}

function startFlashing(): void {
  if (flashInterval) return;
  flashInterval = setInterval(() => {
    isFlashOn = !isFlashOn;
    document.title = isFlashOn
      ? `💬 new message`
      : `(${unreadCount}) ${baseTitle}`;
  }, 1000);
}

function stopFlashing(): void {
  if (flashInterval) {
    clearInterval(flashInterval);
    flashInterval = null;
  }
  isFlashOn = false;
  unreadCount = 0;
  updateTitle();
}

function sendPresence(active: boolean): void {
  const csrf = document.body.dataset.csrfToken || "";
  fetch("/chat/presence", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
    },
    body: JSON.stringify({ active }),
  }).catch(() => {});
}

export function initChat(): void {
  const chatEl = document.getElementById("chat-messages");
  if (!chatEl) return;

  // Auto-scroll to bottom
  chatEl.scrollTop = chatEl.scrollHeight;

  let hasFocus = document.hasFocus();

  window.addEventListener("focus", () => {
    hasFocus = true;
    stopFlashing();
    sendPresence(true);
  });

  window.addEventListener("blur", () => {
    hasFocus = false;
    sendPresence(false);
  });

  // Watch for new messages via MutationObserver
  new MutationObserver(() => {
    // Auto-scroll
    chatEl.scrollTop = chatEl.scrollHeight;

    // Count unread when tab is not focused
    if (!hasFocus) {
      unreadCount++;
      updateTitle();
      startFlashing();
    }
  }).observe(chatEl, { childList: true });
}
