import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { buildSync } from "esbuild";

test("chat counts added messages and focus clears the unread timer", () => {
  let observe;
  let timer = false;
  const listeners = {};
  const chat = { dataset: {}, scrollHeight: 100, scrollTop: 0 };
  const document = {
    title: "",
    hasFocus: () => false,
    getElementById: () => chat,
  };
  class Element {
    classList = { contains: (name) => name === "chat-msg" };
  }
  const context = vm.createContext({
    document,
    Element,
    window: {
      addEventListener: (name, fn) => {
        listeners[name] = fn;
      },
    },
    MutationObserver: class {
      constructor(callback) {
        observe = callback;
      }
      observe() {}
    },
    setInterval: () => {
      timer = true;
      return 1;
    },
    clearInterval: () => {
      timer = false;
    },
    fetch: async () => ({}),
  });
  vm.runInContext(
    buildSync({
      entryPoints: ["src/lib/chat.ts"],
      bundle: true,
      format: "iife",
      globalName: "app",
      write: false,
    }).outputFiles[0].text,
    context,
  );
  context.app.initChat();
  observe([
    {
      addedNodes: [new Element(), { textContent: "whitespace" }, new Element()],
    },
  ]);
  assert.equal(document.title, "(2) 4orm · chat");
  assert.equal(timer, true);
  listeners.blur();
  assert.equal(document.title, "(2) 4orm · chat");
  listeners.focus();
  assert.equal(document.title, "4orm · chat");
  assert.equal(chat.dataset.attention, "focused");
  assert.equal(timer, false);
});
