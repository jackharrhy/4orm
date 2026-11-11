import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { buildSync } from "esbuild";

test("a rejected push registration is an error rather than a subscribed device", async () => {
  const body = { dataset: { vapidKey: "AA", loggedIn: "true" } };
  const context = vm.createContext({
    document: { body, getElementById: () => null },
    window: { PushManager: function () {} },
    navigator: {
      serviceWorker: {
        register: async () => ({
          pushManager: {
            getSubscription: async () => ({ toJSON: () => ({}) }),
          },
        }),
        getRegistrations: async () => [],
      },
      userAgent: "test",
    },
    Notification: { permission: "granted" },
    crypto: { randomUUID: () => "device" },
    localStorage: { getItem: () => "device", setItem() {} },
    fetch: async () => ({ ok: false }),
  });
  vm.runInContext(
    buildSync({
      entryPoints: ["src/lib/push.ts"],
      bundle: true,
      format: "iife",
      globalName: "app",
      write: false,
    }).outputFiles[0].text,
    context,
  );
  context.app.initPushSubscription();
  await new Promise((done) => setImmediate(done));
  assert.equal(body.dataset.pushState, "error");
});
