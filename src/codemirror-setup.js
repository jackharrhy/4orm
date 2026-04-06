import { EditorView, basicSetup } from "codemirror";
import { css } from "@codemirror/lang-css";
import { html } from "@codemirror/lang-html";
import { markdown } from "@codemirror/lang-markdown";
import { EditorState, Compartment } from "@codemirror/state";

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
});

function langExtension(lang) {
  if (lang === "css") return css();
  if (lang === "markdown") return markdown();
  return html();
}

function createEditor(textarea, lang) {
  const langCompartment = new Compartment();
  const parent = document.createElement("div");
  textarea.parentNode.insertBefore(parent, textarea);
  textarea.style.display = "none";

  const view = new EditorView({
    state: EditorState.create({
      doc: textarea.value,
      extensions: [
        basicSetup,
        langCompartment.of(langExtension(lang)),
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

  view._langCompartment = langCompartment;
  return view;
}

// Track editors by textarea id for snippet insertion
window._cmEditors = window._cmEditors || {};

// Auto-upgrade textareas with data-codemirror attribute
document.querySelectorAll("textarea[data-codemirror]").forEach((textarea) => {
  const lang = textarea.dataset.codemirror || "css";
  const view = createEditor(textarea, lang);
  if (textarea.id) {
    window._cmEditors[textarea.id] = view;
  }
});

// Switch editor language (called from format toggle radio buttons)
window.switchEditorLang = function (textareaId, lang) {
  const view = window._cmEditors[textareaId];
  if (view && view._langCompartment) {
    view.dispatch({
      effects: view._langCompartment.reconfigure(langExtension(lang)),
    });
  }
};

// Export for manual use
window.createCodeMirror = createEditor;
