declare global {
  interface Window {
    _mediaFormat: Record<string, string>;
    _cmEditors: Record<string, any>;
    quickUploadMedia: (textareaId: string, fmt: string) => void;
    updateMediaButtons: (textareaId: string) => void;
    insertMediaSnippet: (textareaId: string, type: string) => void;
  }
}

window._mediaFormat = window._mediaFormat || {};
window._cmEditors = window._cmEditors || {};

export function quickUploadMedia(textareaId: string, fmt: string): void {
  const fileInput = document.getElementById(
    "media-upload-file-" + textareaId,
  ) as HTMLInputElement | null;
  if (!fileInput || !fileInput.files?.length) {
    alert("please select a file first");
    return;
  }
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("picker_textarea_id", textareaId);
  formData.append("picker_format", fmt);

  fetch("/api/media/quick-upload", {
    method: "POST",
    body: formData,
  })
    .then((resp) => {
      if (!resp.ok) throw new Error("upload failed");
      return resp.text();
    })
    .then((html) => {
      const picker = document.getElementById("media-picker-" + textareaId);
      if (picker) picker.outerHTML = html;
    })
    .catch((err: Error) => alert(err.message || "upload failed"));
}

export function updateMediaButtons(textareaId: string): void {
  const sel = document.getElementById(
    "media-select-" + textareaId,
  ) as HTMLSelectElement | null;
  if (!sel) return;
  const opt = sel.options[sel.selectedIndex];
  const mime = opt?.dataset.mime || "";
  const wrap = document.getElementById("media-buttons-" + textareaId);
  if (!wrap) return;
  const isImg = mime.startsWith("image/");
  const isVid = mime.startsWith("video/");
  const isAud = mime.startsWith("audio/");
  const show = (cls: string, visible: boolean) => {
    const el = wrap.querySelector(cls) as HTMLElement | null;
    if (el) el.style.display = visible ? "" : "none";
  };
  show(".media-btn-img", isImg);
  show(".media-btn-linked-img", isImg);
  show(".media-btn-video", isVid);
  show(".media-btn-audio", isAud);
}

export function insertMediaSnippet(textareaId: string, type: string): void {
  const sel = document.getElementById(
    "media-select-" + textareaId,
  ) as HTMLSelectElement;
  if (!sel) return;
  const path = "/uploads/" + sel.value;
  const alt = sel.options[sel.selectedIndex]?.dataset.alt || "";
  const fmt = window._mediaFormat[textareaId] || "html";
  let snippet = "";

  if (fmt === "bbcode") {
    if (type === "img") snippet = "[img]" + path + "[/img]";
    else if (type === "linked-img")
      snippet = "[url=" + path + "][img]" + path + "[/img][/url]";
    else if (type === "video") snippet = "[video]" + path + "[/video]";
    else if (type === "audio") snippet = "[audio]" + path + "[/audio]";
    else
      snippet =
        "[url=" +
        path +
        "]" +
        sel.options[sel.selectedIndex].text.trim() +
        "[/url]";
  } else {
    if (type === "img")
      snippet = '<img src="' + path + '" alt="' + alt + '" />';
    else if (type === "linked-img")
      snippet =
        '<a href="' +
        path +
        '"><img src="' +
        path +
        '" alt="' +
        alt +
        '" /></a>';
    else if (type === "video")
      snippet = '<video controls src="' + path + '"></video>';
    else if (type === "audio")
      snippet = '<audio controls src="' + path + '"></audio>';
    else snippet = '<a href="' + path + '">download</a>';
  }

  const cm = window._cmEditors[textareaId];
  if (cm) {
    const pos = cm.state.selection.main.head;
    cm.dispatch({ changes: { from: pos, insert: snippet } });
    cm.focus();
    return;
  }
  const ta = document.getElementById(textareaId) as HTMLTextAreaElement | null;
  if (!ta) return;
  const start = ta.selectionStart || 0;
  const end = ta.selectionEnd || 0;
  ta.value = ta.value.substring(0, start) + snippet + ta.value.substring(end);
  ta.selectionStart = ta.selectionEnd = start + snippet.length;
  ta.focus();
}

window.quickUploadMedia = quickUploadMedia;
window.updateMediaButtons = updateMediaButtons;
window.insertMediaSnippet = insertMediaSnippet;
