/* maidcafe 操作日志 — 每次点击/按键/选择/视图跳转都进本地 events 表，
 * 测试"不对劲"时可精确回放操作序列。批量缓冲 1.5s 发送，
 * 关页用 sendBeacon 兜底不丢尾巴。查询：GET /api/log */

(function () {
  const buf = [];
  let flushT = null;
  window.__mcview = "";

  window.mclog = function (event, detail) {
    buf.push({
      t: Date.now() / 1000,
      page: location.pathname + location.hash,
      view: window.__mcview,
      event,
      detail: String(detail == null ? "" : detail).slice(0, 160),
    });
    if (!flushT) flushT = setTimeout(flush, 1500);
  };

  function flush() {
    flushT = null;
    if (!buf.length) return;
    const body = JSON.stringify({ events: buf.splice(0) });
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/api/log", new Blob([body], { type: "application/json" }));
      } else {
        fetch("/api/log", { method: "POST",
          headers: { "Content-Type": "application/json" }, body }).catch(() => {});
      }
    } catch (_) {}
  }
  addEventListener("pagehide", flush);
  addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
  });

  /* 全局捕获：按钮/链接/折叠/选择器/可点行 */
  addEventListener("click", (e) => {
    const el = e.target.closest(
      "button, a, summary, .ditem, .turn, .wclick, .ph-row");
    if (!el) return;
    const id = el.id ? "#" + el.id : "";
    const cls = (typeof el.className === "string" && el.className)
      ? "." + el.className.split(" ")[0] : "";
    const txt = (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 30);
    mclog("click", `${el.tagName.toLowerCase()}${id}${cls} 「${txt}」`);
  }, true);

  addEventListener("keydown", (e) => {
    if (e.repeat) return;
    if (e.key === " " || /^[jJkKrR]$/.test(e.key)) {
      mclog("key", e.key === " " ? "Space" : e.key.toUpperCase());
    }
  }, true);

  addEventListener("change", (e) => {
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT") {
      mclog("input", `#${e.target.id || "?"} = ${String(e.target.value).slice(0, 40)}`);
    }
  }, true);

  mclog("pageload", document.title);
})();
