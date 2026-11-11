import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { buildSync } from "esbuild";

const flush = () => new Promise((resolve) => setImmediate(resolve));
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
function element(extra = {}) {
  return {
    dataset: {},
    style: {},
    textContent: "",
    innerHTML: "",
    disabled: false,
    setAttribute(name, value) {
      this[name] = value;
    },
    ...extra,
  };
}
function load(file, nodes, fetch) {
  const source = buildSync({
    entryPoints: [file],
    bundle: true,
    format: "iife",
    globalName: "app",
    write: false,
  }).outputFiles[0].text;
  const context = vm.createContext({
    window: {},
    document: { getElementById: (id) => nodes[id] ?? null },
    fetch,
    FormData,
    AbortController,
    alert() {},
  });
  vm.runInContext(source, context);
  return context.window;
}

test("preview ignores stale responses when a newer request finishes first", async () => {
  const first = deferred(),
    second = deferred();
  const preview = element();
  const textarea = element({ value: "first", closest: () => null });
  let requests = 0;
  const app = load(
    "src/lib/forum.ts",
    { post: textarea, "preview-post": preview },
    () => (++requests === 1 ? first.promise : second.promise),
  );
  app.previewPost("post");
  textarea.value = "second";
  app.previewPost("post");
  second.resolve({ ok: true, text: async () => "second preview" });
  await flush();
  first.resolve({ ok: true, text: async () => "stale preview" });
  await flush();
  assert.equal(preview.innerHTML, "second preview");
  assert.equal(preview.dataset.state, "success");
});

test("preview transport failures are visible errors, not rendered gateway HTML", async () => {
  const preview = element();
  const app = load(
    "src/lib/forum.ts",
    {
      post: element({ value: "body", closest: () => null }),
      "preview-post": preview,
    },
    async () => ({ ok: false, text: async () => "bad gateway" }),
  );
  app.previewPost("post");
  await flush();
  assert.equal(preview.dataset.state, "error");
  assert.match(preview.textContent, /try again/i);
  assert.notEqual(preview.innerHTML, "bad gateway");
});

test("upload is single-flight per picker and failure releases it for retry", async () => {
  const response = deferred();
  const button = element(),
    status = element();
  const picker = element({ querySelector: () => button });
  const nodes = {
    "media-upload-file-post": element({ files: [new Blob(["image"])] }),
    "media-picker-post": picker,
    "media-upload-status-post": status,
  };
  let requests = 0;
  const app = load("src/lib/media.ts", nodes, () => {
    requests++;
    return response.promise;
  });
  app.quickUploadMedia("post", "html");
  app.quickUploadMedia("post", "html");
  assert.equal(requests, 1);
  assert.equal(picker.dataset.state, "pending");
  assert.equal(button.disabled, true);
  response.resolve({ ok: false });
  await flush();
  assert.equal(picker.dataset.state, "error");
  assert.equal(button.disabled, false);
  assert.match(status.textContent, /try again/i);
  app.quickUploadMedia("post", "html");
  assert.equal(requests, 2);
  await flush();
});

test("an upload finishing after its picker was replaced does not mark the new picker successful", async () => {
  const response = deferred();
  const original = element({ querySelector: () => null });
  const replacement = element({ querySelector: () => null });
  const nodes = {
    "media-upload-file-post": element({ files: [new Blob(["image"])] }),
    "media-picker-post": original,
  };
  const app = load("src/lib/media.ts", nodes, () => response.promise);
  app.quickUploadMedia("post", "html");
  nodes["media-picker-post"] = replacement;
  response.resolve({ ok: true, text: async () => "old picker" });
  await flush();
  assert.equal(replacement.dataset.state, undefined);
});
