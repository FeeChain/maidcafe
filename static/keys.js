/* Native controls keep their keyboard behavior. The page only owns shortcuts
   when the user is on the learning surface, outside a dialog. */
function cafeShortcut(e) {
  return !e.repeat && !e.isComposing && !e.altKey && !e.ctrlKey && !e.metaKey &&
    !document.querySelector('[role="dialog"]:not(.hidden)') &&
    !e.target.closest("input,textarea,select,button,a,summary,audio,[contenteditable=true]");
}
let cafeReturnFocus = null;
function openCafeDialog(id, closeId) {
  const dlg = document.getElementById(id);
  cafeReturnFocus = document.activeElement;
  dlg.classList.remove("hidden");
  document.getElementById(closeId).focus();
}
function closeCafeDialog(id) {
  document.getElementById(id).classList.add("hidden");
  if (cafeReturnFocus && cafeReturnFocus.isConnected) cafeReturnFocus.focus();
  cafeReturnFocus = null;
}
document.addEventListener("keydown", (e) => {
  const dlg = document.querySelector('[role="dialog"]:not(.hidden)');
  if (!dlg) return;
  if (e.key === "Escape") {
    e.preventDefault();
    dlg.querySelector('[id$="Close"]').click();
    e.stopImmediatePropagation();
  } else if (e.key === "Tab") {
    const items = [...dlg.querySelectorAll("button,input,a[href],select")].filter(el => el.offsetWidth && !el.disabled);
    if (!items.length) return;
    const index = items.indexOf(document.activeElement);
    if (index < 0 || (e.shiftKey && index === 0) || (!e.shiftKey && index === items.length - 1)) {
      e.preventDefault(); items[e.shiftKey ? items.length - 1 : 0].focus();
    }
  }
}, true);
