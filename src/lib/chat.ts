type Attention =
  | { status: "focused" }
  | { status: "unfocused"; unread: number; flash: boolean };
const baseTitle = "4orm · chat";

function sendPresence(active: boolean): void {
  void fetch("/chat/presence", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active }),
  }).catch(() => {});
}

export function initChat(): void {
  const chatEl = document.getElementById("chat-messages");
  if (!chatEl) return;
  let attention: Attention = document.hasFocus()
    ? { status: "focused" }
    : { status: "unfocused", unread: 0, flash: false };
  let timer: ReturnType<typeof setInterval> | null = null;
  function render(): void {
    chatEl!.dataset.attention = attention.status;
    document.title =
      attention.status === "focused" || !attention.unread
        ? baseTitle
        : attention.flash
          ? "💬 new message"
          : `(${attention.unread}) ${baseTitle}`;
  }
  chatEl.scrollTop = chatEl.scrollHeight;
  render();
  window.addEventListener("focus", () => {
    attention = { status: "focused" };
    if (timer !== null) clearInterval(timer);
    timer = null;
    render();
    sendPresence(true);
  });
  window.addEventListener("blur", () => {
    if (attention.status === "focused")
      attention = { status: "unfocused", unread: 0, flash: false };
    render();
    sendPresence(false);
  });
  new MutationObserver((records) => {
    chatEl.scrollTop = chatEl.scrollHeight;
    const added = records.reduce(
      (count, record) =>
        count +
        Array.from(record.addedNodes).filter(
          (node) =>
            node instanceof Element && node.classList.contains("chat-msg"),
        ).length,
      0,
    );
    if (attention.status === "unfocused" && added > 0) {
      attention = { ...attention, unread: attention.unread + added };
      render();
      if (timer === null)
        timer = setInterval(() => {
          if (attention.status === "unfocused")
            attention = { ...attention, flash: !attention.flash };
          render();
        }, 1000);
    }
  }).observe(chatEl, { childList: true });
}
