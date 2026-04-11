import { getCsrfToken } from "./csrf";

declare global {
  interface Window {
    previewPost: (textareaId: string) => void;
    quotePost: (postId: string, author: string, content: string) => void;
    clearQuote: () => void;
  }
}

export function previewPost(textareaId: string): void {
  const ta = document.getElementById(textareaId) as HTMLTextAreaElement | null;
  if (!ta || !ta.value.trim()) return;
  const form = ta.closest("form");
  const formatSel = form?.querySelector(
    'select[name="content_format"]',
  ) as HTMLSelectElement | null;
  const fmt = formatSel ? formatSel.value : "bbcode";
  const preview = document.getElementById("preview-" + textareaId);
  if (!preview) return;

  const fd = new FormData();
  fd.append("content", ta.value);
  fd.append("content_format", fmt);
  fetch("/forum/preview", {
    method: "POST",
    headers: { "X-CSRF-Token": getCsrfToken() },
    body: fd,
  })
    .then((r) => r.text())
    .then((html) => {
      preview.innerHTML = html;
      preview.style.display = "block";
    });
}

export function quotePost(
  postId: string,
  author: string,
  content: string,
): void {
  const setVal = (id: string, val: string) => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (el) el.value = val;
  };
  const setText = (id: string, text: string) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };
  setVal("quoted_post_id", postId);
  setVal("quoted_content", content);
  setVal("quoted_author", author);
  setText("quote-preview-author", author);
  setText(
    "quote-preview-text",
    content.substring(0, 300) + (content.length > 300 ? "..." : ""),
  );
  const qp = document.getElementById("quote-preview");
  if (qp) qp.style.display = "block";
  const details = document.getElementById(
    "reply-details",
  ) as HTMLDetailsElement | null;
  if (details) details.open = true;
  document.getElementById("reply-content")?.focus();
}

export function clearQuote(): void {
  const clear = (id: string) => {
    const el = document.getElementById(id) as HTMLInputElement | null;
    if (el) el.value = "";
  };
  clear("quoted_post_id");
  clear("quoted_content");
  clear("quoted_author");
  const qp = document.getElementById("quote-preview");
  if (qp) qp.style.display = "none";
}

window.previewPost = previewPost;
window.quotePost = quotePost;
window.clearQuote = clearQuote;
