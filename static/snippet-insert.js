function insertSnippet(textareaId, snippet) {
  const cm = window._cmEditors && window._cmEditors[textareaId];
  if (cm) {
    const pos = cm.state.selection.main.head;
    cm.dispatch({ changes: { from: pos, insert: snippet } });
    cm.focus();
    return;
  }
  const el = document.getElementById(textareaId);
  if (!el) return;
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  const before = el.value.slice(0, start);
  const after = el.value.slice(end);
  el.value = before + snippet + after;
  const pos = start + snippet.length;
  el.focus();
  el.setSelectionRange(pos, pos);
}

function insertSnippetFromButton(button, textareaId) {
  insertSnippet(textareaId, button.dataset.snippet || "");
}

function insertSnippetFromSelect(button, textareaId) {
  const select = button.previousElementSibling;
  insertSnippet(textareaId, select.value);
}
