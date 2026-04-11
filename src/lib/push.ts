function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const arr = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) arr[i] = rawData.charCodeAt(i);
  return arr;
}

export function initPushSubscription(): void {
  if (!("serviceWorker" in navigator)) return;

  const vapidKey = document.body.dataset.vapidKey || "";
  const csrfToken = document.body.dataset.csrfToken || "";
  const isLoggedIn = document.body.dataset.loggedIn === "true";

  navigator.serviceWorker.register("/sw.js").then((reg) => {
    if (!vapidKey || !isLoggedIn || !("PushManager" in window)) return;
    reg.pushManager.getSubscription().then((sub) => {
      if (sub) return;
      Notification.requestPermission().then((perm) => {
        if (perm !== "granted") return;
        reg.pushManager
          .subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(vapidKey),
          })
          .then((newSub) => {
            fetch("/api/push/subscribe", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": csrfToken,
              },
              body: JSON.stringify(newSub.toJSON()),
            });
          });
      });
    });
  });
}
