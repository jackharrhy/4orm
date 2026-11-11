function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const arr = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) arr[i] = rawData.charCodeAt(i);
  return arr;
}

function getDeviceId(): string {
  let id = localStorage.getItem("4orm_device_id");
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem("4orm_device_id", id);
  }
  return id;
}

function getDeviceName(): string {
  const ua = navigator.userAgent;
  if (/iPhone|iPad/.test(ua)) return "ios";
  if (/Android/.test(ua)) return "android";
  if (/Mac/.test(ua)) return "mac";
  if (/Windows/.test(ua)) return "windows";
  if (/Linux/.test(ua)) return "linux";
  return "unknown";
}

function sendSubscription(sub: PushSubscription): Promise<void> {
  const payload = sub.toJSON() as Record<string, unknown>;
  payload.device_id = getDeviceId();
  payload.device_name = getDeviceName();
  return fetch("/api/push/subscribe", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  }).then((response) => {
    if (!response.ok) throw new Error("Push registration failed");
  });
}

type PushState =
  | "unavailable"
  | "registering"
  | "disabled"
  | "permission"
  | "denied"
  | "subscribing"
  | "syncing"
  | "subscribed"
  | "error";
let running = false;
function setPushState(state: PushState): void {
  document.body.dataset.pushState = state;
  const status = document.getElementById("push-status");
  if (status) {
    const messages: Record<PushState, string> = {
      unavailable: "Notifications aren't available on this device.",
      registering: "Connecting notifications…",
      disabled: "Notifications aren't available on this device.",
      permission: "Allow notifications in your browser to connect this device.",
      denied: "Notifications are blocked in your browser settings.",
      subscribing: "Connecting notifications…",
      syncing: "Connecting notifications…",
      subscribed: "Notifications are connected on this device.",
      error: "Notifications couldn't connect. Reload to try again.",
    };
    status.textContent = messages[state];
  }
}

export function initPushSubscription(): void {
  if (running) return;
  if (!("serviceWorker" in navigator)) {
    setPushState("unavailable");
    return;
  }
  running = true;
  setPushState("registering");
  void registerPush()
    .catch(() => setPushState("error"))
    .finally(() => {
      running = false;
    });
  void navigator.serviceWorker
    .getRegistrations()
    .then((regs) => {
      for (const reg of regs) {
        if (reg.scope.includes("/static/"))
          void reg.unregister().catch(() => {});
      }
    })
    .catch(() => {});
}

async function registerPush(): Promise<void> {
  const reg = await navigator.serviceWorker.register("/sw.js");
  const vapidKey = document.body.dataset.vapidKey || "";
  if (
    !vapidKey ||
    document.body.dataset.loggedIn !== "true" ||
    !("PushManager" in window)
  ) {
    setPushState("disabled");
    return;
  }
  let subscription = await reg.pushManager.getSubscription();
  if (!subscription) {
    setPushState("permission");
    const permission =
      Notification.permission === "default"
        ? await Notification.requestPermission()
        : Notification.permission;
    if (permission !== "granted") {
      setPushState(permission === "denied" ? "denied" : "permission");
      return;
    }
    setPushState("subscribing");
    subscription = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey),
    });
  }
  setPushState("syncing");
  await sendSubscription(subscription);
  setPushState("subscribed");
}
