/* maidcafe calibration UI — listen-first, two-key rhythm.
 *
 * Flow per word:
 *   audio plays (no text)
 *     Space = recognized by ear  -> mark 3, reveal word to confirm
 *     J     = need to see it     -> mark 1 (= unknown), reveal word
 *   then Space = clear, advance, next audio.
 */

let queue = [];
let idx = 0;
let phase = "listen";   // "listen" | "revealed"
let heard = true;       // stage-1 answer: recognized by ear?
let started = false;
let stats = null;
let audioEl = null;
let probeMode = false;  // 探针式词汇量测定（v1.5）
let probeKind = "dyn";  // dyn=动态折半找边界（默认） | full=全覆盖抽样
let probePer = 3;       // full 模式每块目标样本数
let probeInfo = null;   // dyn 模式：当前 {tier, bracket} 状态
let probeSession = null; // 盲测档案 id（null = 直接写主记录）

const $ = (id) => document.getElementById(id);

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}

function fmtDur(sec) {
  const m = sec / 60;
  return m < 90 ? `${Math.round(m)}分钟` : `${(m / 60).toFixed(1)}小时`;
}

async function loadDecks() {
  const decks = await fetchJSON("/api/decks");
  const sel = $("deckSelect");
  decks.forEach((d) => {
    const o = document.createElement("option");
    o.value = d;
    o.textContent = d;
    sel.appendChild(o);
  });
}

let tiers = [];  // [{tier, total, marked, unknown, bmin, bmax}]

const BAND_NAMES = { 1: "中考", 2: "高考", 3: "四级", 4: "六级",
                     5: "考研", 6: "托福雅思", 7: "GRE", 8: "考纲外" };

function tierLabel(t) {
  let band = "";
  if (t.bmin != null) {
    band = BAND_NAMES[t.bmin] || "";
    if (t.bmax != null && t.bmax !== t.bmin) {
      band += "→" + (BAND_NAMES[t.bmax] || "");
    }
  }
  return band ? `第${t.tier}块 · ${band}` : `第${t.tier}块`;
}

async function loadTiers(keepSelection) {
  tiers = await fetchJSON(`/api/tiers?deck=${encodeURIComponent(currentDeck())}`);
  const sel = $("tierSelect");
  const prev = keepSelection ? sel.value : null;
  while (sel.options.length > 1) sel.remove(1);
  tiers.forEach((t) => {
    const o = document.createElement("option");
    o.value = t.tier;
    o.textContent = `${tierLabel(t)} (${t.marked}/${t.total})`;
    sel.appendChild(o);
  });
  if (prev !== null && [...sel.options].some((o) => o.value === prev)) {
    sel.value = prev;
  } else {
    // default: first block that still has unmarked words
    const first = tiers.find((t) => t.marked < t.total);
    sel.value = first ? String(first.tier) : "all";
  }
}

function currentDeck() { return $("deckSelect").value; }
function currentMode() { return $("modeSelect").value; }
function currentTier() { return $("tierSelect").value; }

async function loadStats() {
  const scope = currentTier() === "all" ? "全部" : `本块`;
  stats = await fetchJSON(
    `/api/stats?deck=${encodeURIComponent(currentDeck())}&tier=${currentTier()}`);
  const remain = stats.total - stats.marked;
  const overallRemain = stats.overall_total - stats.overall_marked;
  let eta = "";
  if (remain > 0) {
    eta = ` · 剩≈${fmtDur(remain * stats.pace)}`;
    if (currentTier() !== "all" && overallRemain > remain) {
      eta += `（全库≈${fmtDur(overallRemain * stats.pace)}）`;
    }
  }
  $("statsBar").innerHTML =
    `${scope}已标 <b>${stats.marked}</b>/${stats.total} · ` +
    `<span class="s3">认识 ${stats.ear_known}</span> · ` +
    `<span class="s1">生词 ${stats.unknown + stats.eye_only}</span>` + eta;
  const pct = stats.total ? (stats.marked / stats.total) * 100 : 0;
  $("progressFill").style.width = pct.toFixed(2) + "%";
}

async function loadQueue() {
  $("statsBar").textContent = "加载词库中…";
  queue = await fetchJSON(
    `/api/words?deck=${encodeURIComponent(currentDeck())}&mode=${currentMode()}` +
    `&tier=${currentTier()}`);
  idx = 0;
  showCurrent();
}

function cur() { return queue[idx]; }

function playAudio() {
  const w = cur();
  if (!w || !w.has_audio) return;
  if (audioEl) { audioEl.pause(); }
  audioEl = new Audio("/audio/" + encodeURIComponent(w.word));
  audioEl.play().catch(() => {});
}

function showDone() {
  if (probeMode) { showProbeResult(); return; }
  $("card").classList.add("hidden");
  $("doneCard").classList.remove("hidden");
  const t = currentTier();
  const hasNext = t !== "all" && tiers.some((x) => x.tier === parseInt(t, 10) + 1);
  const remaining = stats ? stats.total - stats.marked : 0;
  $("doneTitle").textContent =
    t === "all" ? "这一轮结束 🎉"
      : remaining > 0 ? `第${t}块先到这里 ☕` : `第${t}块过完了 🎉`;
  $("nextTierBtn").classList.toggle("hidden", !hasNext);
  $("resumeBtn").classList.toggle("hidden", remaining <= 0);
  const da = $("doneArt");           // 庆祝画稿只在整块真过完时亮
  if (da) da.classList.toggle("hidden", remaining > 0);
  $("resumeBtn").textContent = `继续过完这一块（剩 ${remaining} 词）`;
  if (stats) {
    $("doneStats").innerHTML =
      `认识 <b>${stats.ear_known}</b> · 生词 <b>${stats.unknown + stats.eye_only}</b> · ` +
      `已标 ${stats.marked}/${stats.total}`;
  }
  loadTiers(true);
}

function showCurrent() {
  if (!queue.length || idx >= queue.length) {
    if (probeMode) {
      probeKind === "dyn" ? probeNext() : showProbeResult(null);
      return;
    }
    loadStats().then(showDone);
    return;
  }
  probeMode ? renderProbeStats() : loadStats();
  $("probeCard").classList.add("hidden");
  $("doneCard").classList.add("hidden");
  $("card").classList.remove("hidden");
  phase = "listen";
  const w = cur();

  $("listenState").classList.remove("hidden");
  $("answerState").classList.add("hidden");
  $("judgeBtns").classList.remove("hidden");
  $("nextBtns").classList.add("hidden");

  if (w.has_audio) {
    $("playBtn").classList.remove("hidden");
    $("noAudioNote").classList.add("hidden");
    $("wordPreview").classList.add("hidden");
    playAudio();
  } else {
    // no audio: judge by sight instead
    $("playBtn").classList.add("hidden");
    $("noAudioNote").classList.remove("hidden");
    $("wordPreview").textContent = w.word;
    $("wordPreview").classList.remove("hidden");
  }
}

/* Stage 1 (listen): Space = heard it, J = missed it. Either way, reveal. */
function judge(didHear) {
  const w = cur();
  if (!w || phase !== "listen") return;
  phase = "revealed";
  heard = didHear;
  $("listenState").classList.add("hidden");
  $("answerState").classList.remove("hidden");
  $("judgeBtns").classList.add("hidden");
  $("nextBtns").classList.remove("hidden");
  $("markTag").textContent = didHear ? "听出来了" : "没听出来 → 生词";
  $("markTag").className = "mark-tag " + (didHear ? "mt3" : "mt1");
  $("wordText").textContent = w.word;
  $("phoneticText").textContent = w.phonetic || "";
  $("defText").textContent = w.definition || "";
  $("exEn").textContent = w.example_en || "";
  $("exCn").textContent = w.example_cn || "";
  $("srcText").textContent = (w.sources || []).join(" · ");
}

/* Stage 2 (revealed): Space = know it by sight, J = don't. Writes the final
 * status and advances. Space+Space=3 known; J+Space=2 (eye-only, counts as
 * 生词 in the UI but kept distinct in the DB); any ending in J = 1 unknown. */
async function finalize(canRead) {
  const w = cur();
  if (!w || phase !== "revealed") return;
  const status = heard && canRead ? 3 : (!heard && canRead ? 2 : 1);
  idx += 1;
  showCurrent();
  await fetchJSON("/api/mark", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word: w.word, status,
                           src: probeMode ? "probe" : "scan",
                           session: probeSession || undefined }),
  });
  if (!probeMode) loadStats();
}

/* ---------------- 探针式词汇量测定 ---------------- */

let probePace = 4.5;  // 秒/词，开针时从 /api/stats 取实测值

const sessParam = () => (probeSession ? `&session=${probeSession}` : "");

async function startProbe(kind, fresh) {
  started = true;
  probeMode = true;
  probeKind = kind;
  if (fresh) {
    const r = await fetchJSON("/api/probe_session_start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    });
    probeSession = r.session;
  }
  $("startOverlay").classList.add("hidden");
  try {
    const s = await fetchJSON(`/api/stats?deck=${encodeURIComponent(currentDeck())}&tier=all`);
    stats = s;
    if (s.pace) probePace = s.pace;
  } catch (_) {}
  if (kind === "dyn") { probeNext(); return; }
  queue = await fetchJSON(`/api/probe_queue?deck=${encodeURIComponent(currentDeck())}&per=${probePer}${sessParam()}`);
  idx = 0;
  if (!queue.length) { showProbeResult(null); return; }
  showCurrent();
}

/* 动态折半：向服务端要下一批 3 词；服务端每次从全部标记重放搜索，
 * 所以中途退出、明天再来都严格接着走 */
async function probeNext() {
  const r = await fetchJSON(`/api/probe_next?deck=${encodeURIComponent(currentDeck())}${sessParam()}`);
  if (r.done) { showProbeResult(r); return; }
  probeInfo = r;
  queue = r.words;
  idx = 0;
  showCurrent();
}

function renderProbeStats() {
  const tag = probeSession ? `盲测#${probeSession} · ` : "";
  if (probeKind === "dyn" && probeInfo) {
    const [lo, hi] = probeInfo.bracket;
    $("statsBar").innerHTML =
      `🔍 ${tag}折半试探第 <b>${probeInfo.tier}</b> 块 · 边界区间 (${lo}, ${hi}) · ` +
      `本轮 ${idx}/${queue.length}`;
    $("progressFill").style.width = "0%";
    return;
  }
  const remain = queue.length - idx;
  $("statsBar").innerHTML =
    `🔍 ${tag}探针 <b>${idx}</b>/${queue.length}` +
    (remain > 0 ? ` · 剩≈${fmtDur(remain * probePace)}` : "");
  $("progressFill").style.width =
    (queue.length ? (idx / queue.length) * 100 : 0).toFixed(2) + "%";
}

const fmtN = (x) => x.toLocaleString("zh-CN");

async function showProbeResult(r) {
  $("card").classList.add("hidden");
  $("doneCard").classList.add("hidden");
  $("probeCard").classList.remove("hidden");
  const bd = $("probeBoundary");
  if (r && r.done) {
    bd.innerHTML =
      `边界 ≈ 第 <b>${r.boundary}</b> 块` +
      (r.boundary_band ? `（${BAND_NAMES[r.boundary_band] || ""}段）` : "") +
      ` · 折半区间 (${r.bracket[0]}, ${r.bracket[1]}) · 共测 ${r.probe_words} 词`;
    bd.classList.remove("hidden");
  } else {
    bd.classList.add("hidden");
  }
  $("adoptBtn").classList.toggle("hidden", !probeSession);
  $("discardBtn").classList.toggle("hidden", !probeSession);
  if (probeSession) {  // 结档：服务端存一份结果快照进历史
    fetchJSON("/api/probe_session_finish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: probeSession }),
    }).catch(() => {});
  }
  $("probeNums").innerHTML = "计算中…";
  const v = await fetchJSON(`/api/vocab_estimate?deck=${encodeURIComponent(currentDeck())}${sessParam()}`);
  // 有未测块时数字是外推，标 ± 会假装精确——测满一轮才显示置信区间
  const ci = v.unmeasured_blocks === 0;
  $("probeNums").innerHTML =
    `听得出 ≈ <b>${fmtN(v.listening)}</b>${ci ? `<small>±${v.ci95_listen}</small>` : ""} · ` +
    `看得懂 ≈ <b>${fmtN(v.reading)}</b>${ci ? `<small>±${v.ci95_read}</small>` : ""} 词` +
    `<div class="hint-line">样本 ${fmtN(v.sampled)}/${fmtN(v.total_words)} · ` +
    `精确 ${v.exact_blocks} 块 · 推定 ${v.probe_blocks} 块` +
    (v.unmeasured_blocks ? ` · 未测 ${v.unmeasured_blocks} 块（按邻块推定）` : "") +
    `</div>`;
  $("probeBands").innerHTML = v.bands.map((b) =>
    `<div class="row"><span class="bname">${BAND_NAMES[b.band] || "其他"}</span>` +
    `<span class="bbar"><i style="width:${(b.read / b.total * 100).toFixed(1)}%"></i>` +
    `<i class="lst" style="width:${(b.listen / b.total * 100).toFixed(1)}%"></i></span>` +
    `<span class="bnum">听 ${fmtN(b.listen)} · 读 ${fmtN(b.read)} / ${fmtN(b.total)}</span></div>`
  ).join("");
  loadVocabLine();
}

/* 欢迎卡上的「上次测定」一行（测过完整一轮才显示） */
async function loadVocabLine() {
  try {
    const v = await fetchJSON(`/api/vocab_estimate?deck=${encodeURIComponent(currentDeck())}`);
    if (v.unmeasured_blocks === 0 && v.sampled > 0) {
      $("vocabLine").innerHTML =
        `当前测定：听得出 ≈ <b>${fmtN(v.listening)}</b> · 看得懂 ≈ <b>${fmtN(v.reading)}</b> 词`;
      $("vocabLine").classList.remove("hidden");
    }
  } catch (_) {}
}

function endRound() {
  if (!started) return;
  if (probeMode) { showProbeResult(null); return; }  // 中止探针，直接看结果
  idx = queue.length;
  showCurrent();
}

async function start() {
  if (started) return;
  started = true;
  $("startOverlay").classList.add("hidden");
  await loadTiers(false);
  loadQueue();
}

function gotoNextTier() {
  const t = parseInt(currentTier(), 10);
  $("tierSelect").value = String(t + 1);
  loadQueue();
}

document.addEventListener("keydown", (e) => {
  if (!started) { start(); e.preventDefault(); return; }
  if (e.repeat) return;
  switch (e.key) {
    case " ":
      e.preventDefault();
      phase === "listen" ? judge(true) : finalize(true);
      break;
    case "j": case "J":
      phase === "listen" ? judge(false) : finalize(false);
      break;
    case "k": case "K": case "r": case "R":
      playAudio();
      break;
  }
});

$("startBtn").addEventListener("click", start);
$("probeBtn").addEventListener("click", (e) => { e.stopPropagation(); startProbe("dyn"); });
$("probeMoreBtn").addEventListener("click", async () => {
  probeKind = "full";
  for (; probePer <= 12; probePer += 3) {
    queue = await fetchJSON(`/api/probe_queue?deck=${encodeURIComponent(currentDeck())}&per=${probePer}`);
    if (queue.length) break;
  }
  idx = 0;
  if (!queue.length) { $("probeMoreBtn").textContent = "没有可抽的词了"; return; }
  showCurrent();
});
$("probeExitBtn").addEventListener("click", async () => {
  probeMode = false;
  probeSession = null;
  $("probeCard").classList.add("hidden");
  await loadTiers(false);
  loadQueue();
  loadProbeHist();
});

async function sessionAction(url, msg) {
  await fetchJSON(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: probeSession }),
  });
  probeSession = null;
  loadVocabLine();
  $("probeExitBtn").click();
}
$("adoptBtn").addEventListener("click", () => {
  if (confirm("把本次盲测的标记合并进主记录？（同词覆写旧标记）"))
    sessionAction("/api/probe_session_adopt");
});
$("discardBtn").addEventListener("click", () => {
  if (confirm("删除本次盲测档案？")) sessionAction("/api/probe_session_discard");
});
$("probeFreshBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  startProbe("dyn", true);
});

/* 历史测定列表（盲测档案；可回头采用或删除） */
async function loadProbeHist() {
  try {
    const list = await fetchJSON("/api/probe_sessions");
    if (!list.length) { $("probeHist").classList.add("hidden"); return; }
    $("probeHist").classList.remove("hidden");
    $("probeHistList").innerHTML = list.map((s) => {
      const d = new Date(s.ts * 1000).toLocaleDateString("zh-CN",
        { month: "numeric", day: "numeric" });
      const r = s.result || {};
      const nums = r.listening != null
        ? `听 ${fmtN(r.listening)} · 读 ${fmtN(r.reading)}` +
          (r.boundary ? ` · 边界 第${r.boundary}块` : "")
        : "无结果";
      const act = s.status === "adopted"
        ? `<span class="s3">已采用</span>`
        : `<button class="mk small" data-adopt="${s.id}">采用</button>` +
          `<button class="mk small" data-del="${s.id}">删除</button>`;
      return `<div class="ph-row">#${s.id} · ${d} · ${nums} ${act}</div>`;
    }).join("");
    $("probeHistList").querySelectorAll("[data-adopt]").forEach((b) =>
      b.addEventListener("click", async () => {
        if (!confirm("把该档案的标记合并进主记录？（同词覆写旧标记）")) return;
        await fetchJSON("/api/probe_session_adopt", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session: parseInt(b.dataset.adopt, 10) }),
        });
        loadVocabLine(); loadProbeHist();
      }));
    $("probeHistList").querySelectorAll("[data-del]").forEach((b) =>
      b.addEventListener("click", async () => {
        if (!confirm("删除该档案？")) return;
        await fetchJSON("/api/probe_session_discard", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session: parseInt(b.dataset.del, 10) }),
        });
        loadProbeHist();
      }));
  } catch (_) {}
}
$("playBtn").addEventListener("click", (e) => { e.currentTarget.blur(); playAudio(); });
$("btnKnow").addEventListener("click", (e) => { e.currentTarget.blur(); judge(true); });
$("btnShow").addEventListener("click", (e) => { e.currentTarget.blur(); judge(false); });
$("btnNext").addEventListener("click", (e) => { e.currentTarget.blur(); finalize(true); });
$("btnOops").addEventListener("click", (e) => { e.currentTarget.blur(); finalize(false); });
$("endBtn").addEventListener("click", (e) => { e.currentTarget.blur(); endRound(); });
$("resumeBtn").addEventListener("click", () => loadQueue());
$("nextTierBtn").addEventListener("click", () => gotoNextTier());
$("deckSelect").addEventListener("change", async () => {
  if (started) { await loadTiers(false); loadQueue(); }
});
$("modeSelect").addEventListener("change", () => { if (started) loadQueue(); });
$("tierSelect").addEventListener("change", () => { if (started) loadQueue(); });

/* --- dismissable key-hint bar --- */
function setHints(visible) {
  $("hintBar").classList.toggle("hidden", !visible);
  try { localStorage.setItem("maidcafe_hints", visible ? "1" : "0"); } catch (_) {}
}
$("hintClose").addEventListener("click", () => setHints(false));
$("hintToggle").addEventListener("click", (e) => {
  e.currentTarget.blur();
  setHints($("hintBar").classList.contains("hidden"));
});
try {
  if (localStorage.getItem("maidcafe_hints") === "0") setHints(false);
} catch (_) {}

/* D4: 回访「从哪继续」——有到期词就把客人引去听力室 */
(async function continueBar() {
  try {
    const s = await fetchJSON("/api/daily_status");
    if (s.due > 0) {
      const bar = $("continueBar");
      bar.innerHTML =
        `今天有 <b>${s.due}</b> 个词等着与你重逢 —— <a href="/listen">去听力室 ☕</a>`;
      bar.classList.remove("hidden");
    }
  } catch (_) {}
})();

loadDecks();
loadStats();
loadVocabLine();
loadProbeHist();
