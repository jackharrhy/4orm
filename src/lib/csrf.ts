export function getCsrfToken(): string {
  return document.body.dataset.csrfToken || "";
}

export function initCsrfFormInterceptor(): void {
  document.addEventListener("submit", (e: Event) => {
    const form = e.target as HTMLFormElement;
    if (form.method && form.method.toLowerCase() !== "post") return;
    if (form.hasAttribute("hx-post")) return;
    e.preventDefault();
    const formData = new FormData(form);
    fetch(form.action || window.location.href, {
      method: "POST",
      headers: { "X-CSRF-Token": getCsrfToken() },
      body: formData,
    }).then((resp) => {
      if (resp.redirected) {
        window.location.href = resp.url;
      } else if (resp.ok) {
        window.location.reload();
      } else {
        resp.text().then((t) => {
          document.open();
          document.write(t);
          document.close();
        });
      }
    });
  });
}

export function initHtmxErrorHandler(): void {
  document.addEventListener("htmx:responseError", ((e: CustomEvent) => {
    if (e.detail.xhr?.responseText) {
      const form =
        (e.detail.elt as HTMLElement).closest("form") ||
        (e.detail.elt as HTMLElement);
      const existing = form.querySelector(".htmx-error");
      if (existing) existing.remove();
      const div = document.createElement("div");
      div.className = "htmx-error";
      div.innerHTML = e.detail.xhr.responseText;
      form.appendChild(div);
      setTimeout(() => div.remove(), 5000);
    }
  }) as EventListener);
}
