import { EditorView, basicSetup } from "codemirror";
import { indentWithTab } from "@codemirror/commands";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { markdown } from "@codemirror/lang-markdown";
import { EditorState, Compartment } from "@codemirror/state";
import { keymap } from "@codemirror/view";

declare global {
  interface Window {
    _cmEditors: Record<string, any>;
    switchEditorLang: (textareaId: string, lang: string) => void;
    createCodeMirror: (textarea: HTMLTextAreaElement, lang: string) => any;
  }
}

const theme = EditorView.theme({
  "&": {
    backgroundColor: "#fff",
    color: "#111",
    border: "2px inset #ccc",
    fontSize: "13px",
  },
  ".cm-content": {
    padding: "8px 4px",
    caretColor: "#111",
    fontFamily: "monospace",
  },
  ".cm-gutters": {
    backgroundColor: "#f5f5f5",
    color: "#999",
    border: "none",
    paddingRight: "4px",
  },
  ".cm-activeLine": { backgroundColor: "#f0f4ff" },
  ".cm-activeLineGutter": { backgroundColor: "#f0f4ff" },
  "&.cm-focused": { outline: "2px solid #00ccff" },
  ".cm-scroller": { padding: "4px 0" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground": {
    backgroundColor: "#b4d7ff !important",
  },
  ".cm-cursor": { borderLeftColor: "#111", borderLeftWidth: "2px" },
  ".cm-matchingBracket": {
    backgroundColor: "#c8e6c9",
    outline: "1px solid #4caf50",
  },
  ".cm-selectionMatch": { backgroundColor: "#e0e0e0" },
});

function langExtension(lang: string) {
  if (lang === "css") return css();
  if (lang === "markdown") return markdown();
  return html();
}

function createEditor(textarea: HTMLTextAreaElement, lang: string) {
  const langCompartment = new Compartment();
  const parent = document.createElement("div");
  textarea.parentNode!.insertBefore(parent, textarea);
  textarea.style.display = "none";

  const view = new EditorView({
    state: EditorState.create({
      doc: textarea.value,
      extensions: [
        basicSetup,
        langCompartment.of(langExtension(lang)),
        keymap.of([indentWithTab]),
        EditorView.lineWrapping,
        theme,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            textarea.value = update.state.doc.toString();
          }
        }),
      ],
    }),
    parent,
  });

  (view as any)._langCompartment = langCompartment;
  return view;
}

// Track editors by textarea id for snippet insertion
window._cmEditors = window._cmEditors || {};

// Auto-upgrade textareas with data-codemirror attribute
document
  .querySelectorAll<HTMLTextAreaElement>("textarea[data-codemirror]")
  .forEach((textarea) => {
    const lang = textarea.dataset.codemirror || "css";
    const view = createEditor(textarea, lang);
    if (textarea.id) {
      window._cmEditors[textarea.id] = view;
    }
  });

// Switch editor language (called from format toggle radio buttons)
window.switchEditorLang = function (textareaId: string, lang: string) {
  const view = window._cmEditors[textareaId];
  if (view && view._langCompartment) {
    view.dispatch({
      effects: view._langCompartment.reconfigure(langExtension(lang)),
    });
  }
};

// Export for manual use
window.createCodeMirror = createEditor;
