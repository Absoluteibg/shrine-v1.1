// SHRINE admin — confirmation prompts for destructive actions.
//
// Attached via addEventListener, not inline onsubmit="" attributes, so
// this works under the strict Content-Security-Policy set in
// app/main.py (default-src 'self' has no 'unsafe-inline' exception).
document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    }
  });
});
