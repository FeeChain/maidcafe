/* 词根词缀行（FLOW 工具页 · 2026-10-13）：释义保持英文原文，标签用中文。
   主页与对话史页共用；m 为 /api/lookup 的 morph 字段，拆不出返回空串。 */
function morphHTML(m) {
  if (!m) return "";
  const esc = (s) => String(s).replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const parts = (m.parts || []).map((p) =>
    `<span class="mp mp-${p.kind}"><b>${esc(p.form)}</b>` +
    (p.meaning ? ` <i>${esc(p.meaning)}</i>` : "") + "</span>")
    .join('<span class="mp-plus">+</span>');
  let html = parts
    ? `<div class="morph-parts">${parts}` +
      (m.auto ? '<span class="morph-auto">自动拆分</span>' : "") + "</div>"
    : "";
  if (m.family && m.family.length)
    html += `<div class="morph-line"><span class="morph-tag">同根</span>${m.family.map(esc).join(" · ")}</div>`;
  if (m.derived && m.derived.length)
    html += `<div class="morph-line"><span class="morph-tag">派生</span>${m.derived.map(esc).join(" · ")}</div>`;
  return html;
}
