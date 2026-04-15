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
  }).then(() => {});
}

export function initPushSubscription(): void {
  if (!("serviceWorker" in navigator)) return;

  const vapidKey = document.body.dataset.vapidKey || "";
  const isLoggedIn = document.body.dataset.loggedIn === "true";

  navigator.serviceWorker.register("/sw.js").then((reg) => {
    if (!vapidKey || !isLoggedIn || !("PushManager" in window)) return;

    reg.pushManager.getSubscription().then((existing) => {
      if (existing) {
        // Already subscribed -- re-send to ensure server has it
        sendSubscription(existing);
        return;
      }

      if (Notification.permission === "granted") {
        reg.pushManager
          .subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(vapidKey),
          })
          .then((newSub) => sendSubscription(newSub));
      } else if (Notification.permission === "default") {
        Notification.requestPermission().then((perm) => {
          if (perm !== "granted") return;
          reg.pushManager
            .subscribe({
              userVisibleOnly: true,
              applicationServerKey: urlBase64ToUint8Array(vapidKey),
            })
            .then((newSub) => sendSubscription(newSub));
        });
      }
    });
  });

  // Clean up old service workers from /static/ scope
  navigator.serviceWorker.getRegistrations().then((regs) => {
    for (const reg of regs) {
      if (reg.scope.includes("/static/")) {
        reg.unregister();
      }
    }
  });
}
