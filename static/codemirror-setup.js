import {
  EditorView,
  basicSetup,
} from "https://esm.sh/codemirror@6.0.1?bundle-deps";
import { css } from "https://esm.sh/@codemirror/lang-css@6.3.1?bundle-deps";
import { html } from "https://esm.sh/@codemirror/lang-html@6.4.9?bundle-deps";
import { EditorState } from "https://esm.sh/@codemirror/state@6.5.2?bundle-deps";

const darkTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#1e1e1e",
      color: "#d4d4d4",
      border: "2px inset #ccc",
      fontSize: "13px",
    },
    ".cm-content": { caretColor: "#fff" },
    ".cm-gutters": {
      backgroundColor: "#1e1e1e",
      color: "#858585",
      border: "none",
    },
    ".cm-activeLine": { backgroundColor: "#2a2a2a" },
    ".cm-activeLineGutter": { backgroundColor: "#2a2a2a" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": {
      backgroundColor: "#264f78",
    },
    ".cm-cursor": { borderLeftColor: "#fff" },
  },
  { dark: true },
);

function createEditor(textarea, lang) {
  const langExt = lang === "css" ? css() : html();
  const parent = document.createElement("div");
  textarea.parentNode.insertBefore(parent, textarea);
  textarea.style.display = "none";

  const view = new EditorView({
    state: EditorState.create({
      doc: textarea.value,
      extensions: [
        basicSetup,
        langExt,
        darkTheme,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            textarea.value = update.state.doc.toString();
          }
        }),
      ],
    }),
    parent,
  });

  return view;
}

// Auto-upgrade textareas with data-codemirror attribute
document.querySelectorAll("textarea[data-codemirror]").forEach((textarea) => {
  const lang = textarea.dataset.codemirror || "css";
  const view = createEditor(textarea, lang);
  if (textarea.id) {
    window._cmEditors[textarea.id] = view;
  }
});

// Track editors by textarea id for snippet insertion
window._cmEditors = window._cmEditors || {};

// Export for manual use
window.createCodeMirror = createEditor;
