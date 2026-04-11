export function convertTimes(): void {
  document.querySelectorAll<HTMLTimeElement>("time[datetime]").forEach((el) => {
    const d = new Date(el.getAttribute("datetime")!);
    if (isNaN(d.getTime())) return;
    const fmt = el.dataset.fmt || "full";

    if (fmt === "relative") {
      const diff = (Date.now() - d.getTime()) / 1000;
      if (diff < 60) el.textContent = "just now";
      else if (diff < 3600) el.textContent = Math.floor(diff / 60) + "m ago";
      else if (diff < 86400) el.textContent = Math.floor(diff / 3600) + "h ago";
      else if (diff < 604800)
        el.textContent = Math.floor(diff / 86400) + "d ago";
      else
        el.textContent = d.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        });
    } else if (fmt === "date") {
      el.textContent = d.toLocaleDateString();
    } else if (fmt === "time") {
      el.textContent = d.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
      });
    } else {
      el.textContent = d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
    el.classList.add("converted");
  });
}

export function initTimeConversion(): void {
  convertTimes();
  document.addEventListener("htmx:afterSwap", convertTimes);
}
