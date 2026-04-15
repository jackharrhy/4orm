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
