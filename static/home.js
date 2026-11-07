/* Arrival → window-seat menu → word cards / a requested story.
 * Recall is optional, only covers seen words, and saves each answer. */

const $ = (id) => document.getElementById(id);
async function fetchJSON(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json();
  if (!r.ok) { const error = new Error(data.error || '暂时没有连到店内服务。'); error.code = data.code; throw error; }
  return data;
}
const POST = (url, body) => fetchJSON(url, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});
const fmtN = (x) => x.toLocaleString("zh-CN");

let view = "";           // vNew | vEmpty | vLearn | vExam | vExamDone | vDone
let sessionWords = [];   // 本次会话的一份词（/api/session 现抓后洗牌，零落库）
let sessionTotal = 0;    // 整份词数（顶行/庆祝用）
let viewedOrder = [];    // 翻开顺序（篮子按它攒）
let inPot = new Set();   // 已进过锅（当过对话目标词）的词——不落库，关掉即清
let pool = [];           // 还没考过的词（学习循环用，乱序）
let li = 0;              // 学习卡游标
let lRevealed = false;
let audioEl = null;
let sceneGroup = null;   // 最近一场对话的目标词（≤5 个）
let sceneWatch = null;
let exQueue = [];        // 本轮考试队列
let exIdx = 0;
let exPhase = "listen";
let examSaving = false;
let exPassed = 0; let exFailed = 0;

function show(v) {
  ["vNew", "vSeat", "vIntro", "vEmpty", "vLearn", "vListen", "vExam", "vExamDone",
   "vDone"].forEach((id) => $(id).classList.toggle("hidden", id !== v));
  if (v !== "vSeat") $("sampleAudio").pause();
  if (audioEl) audioEl.pause();
  lsPlaying = false;
  if (v === "vSeat") refreshStorySetup();
  view = v;
  window.__mcview = v;
  mclog("view", v);
}

function toast(msg) {
  $("toastMsg").textContent = msg;
  $("toast").classList.remove("hidden");
  setTimeout(() => $("toast").classList.add("hidden"), 4000);
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function playWord(w) {
  if (!w || !w.has_audio) return;
  if (audioEl) audioEl.pause();
  audioEl = new Audio("/audio/" + encodeURIComponent(w.word));
  audioEl.play().catch(() => {
    // 开门即学：首个音可能被浏览器拦自动播放，给一句提示，任意交互后恢复
    const h = $("lHint");
    if (h && view === "vLearn") h.textContent = "按 K 或点喇叭听发音（浏览器拦了自动播放）";
  });
}

/* ---------------- 主状态机 ---------------- */
/* 开门即学：打开=S2，关掉=结束。没有「每天/任务」概念——
 * 每次打开现抓一份（先复习后新词，总量用户设，FLOW §4），背完就是背完；
 * 唯一落库的是考试结果（权重即时更新），其余什么都不记。 */
async function boot() {
  const s = await fetchJSON("/api/home_status");
  resumeScene();   // 煮着的对话在任何视图都继续盯（不在学习页就 toast 通知）
  const params = new URLSearchParams(location.search);
  if (params.has("welcome")) { show("vNew"); return; }
  if (params.has("menu")) { show("vSeat"); return; }
  if (!s.calibrated && !s.seated) { show("vNew"); return; }
  await loadSession();
  if (!pool.length) { show("vEmpty"); return; }  // 生词池和复习都空：去攒词
  // 刚测完过来的那一次：先给个「开始这一轮」的确认卡，别太突兀
  if (new URLSearchParams(location.search).get("fresh")) {
    history.replaceState(null, "", "/");
    $("introLine").innerHTML =
      `这一轮为你备了 <b>${pool.length}</b> 个词` +
      `<span class="hint-line">（你的生词 + 边界之后按难度推定的词）</span>`;
    show("vIntro");
    return;
  }
  enterLearn();                                  // 其余一律直落 S2
}

let passed = new Set();   // 本次会话已考过的词
let sessionRest = false;  // 复习占满整份、没有新词（FLOW §4 休息一份）

/* 学习顺序 = 每份现抓后洗牌一次的乱序，循环保持同序（v4 用户裁决） */
function rebuildPool() {
  pool = sessionWords.filter((w) => !passed.has(w.word));
  li = 0;
}

async function loadSession() {
  const r = await fetchJSON("/api/session");
  sessionWords = shuffle(r.words.slice());   // 乱序过一遍（循环保持同序）
  sessionTotal = r.words.length;
  sessionRest = !!r.rest;
  passed = new Set();
  viewed = new Set();
  viewedOrder = [];
  inPot = new Set();
  rebuildPool();
  cycles = 0;
  mclog("session", `${sessionWords.length} 词: ${sessionWords.map((w) => w.word).slice(0, 8).join(",")}`);
}

/* ---------------- 学习循环 ---------------- */
function enterLearn() {
  if (!pool.length) { renderDone(); return; }
  show("vLearn");
  renderLearnTop();
  renderBrew();
  showLearnCard();
}

/* ---- 篮子：翻开过、没考过、没进过锅的词按翻开顺序攒进下一杯，5 个封顶 ----
   盲听产品不剧透：只报数，不显示具体是哪些词（2026-09-22 用户裁决 v4） */
function brewQueue() {
  return viewedOrder
    .filter((w) => !passed.has(w) && !inPot.has(w))
    .slice(0, 5);
}

function renderBrew() {
  const btn = $("brewBtn");
  if (!btn) return;
  if (getPending()) {
    btn.disabled = false;
    btn.textContent = "☕ 灶上煮着——点击看进度";
    return;
  }
  const q = brewQueue();
  btn.disabled = !q.length;
  btn.textContent = q.length
    ? `☕ 给这 ${q.length} 个词来一场对话`
    : "☕ 翻开的词会攒进下一杯（最多 5 个）";
}

function renderLearnTop() {
  const n = pool.filter(w => viewed.has(w.word)).length;
  $("learnProgress").textContent = "窗边 · 自由翻阅";
  $("examBtn").textContent = n ? `回想刚看的 ${n} 个词` : "翻一张卡就可以回想";
  $("examBtn").disabled = !n;
  $("lsExamBtn").disabled = !n;
  $("restLine").classList.toggle("hidden", !sessionRest);
}

function curLearn() { return pool[li % pool.length]; }

function showLearnCard() {
  const w = curLearn();
  if (!w) return;
  lRevealed = false;
  $("newTag").textContent = w.is_new ? "新词" : "复习";
  $("newTag").classList.remove("hidden");
  $("lWord").textContent = "· · ·";
  $("lWord").classList.add("veiled-word");
  $("lPhon").textContent = "";
  $("lDef").classList.add("hidden");
  $("lMorph").innerHTML = "";               // 遮着时不显示（盲听不剧透）
  $("lRevealBtn").classList.remove("hidden");
  $("lNextBtn").classList.add("hidden");
  $("lPlayBtn").disabled = !w.has_audio;
  $("lHint").textContent = w.has_audio ? "先听听，想起词义后再翻卡。K 可以重听。" : "这个词暂时没有录音，翻卡看看它的意思。";
  playWord(w);
}

let viewed = new Set();   // 本次会话翻开过的词（篮子攒词用，不落库）

function revealLearn() {
  const w = curLearn();
  lRevealed = true;
  if (!viewed.has(w.word)) viewedOrder.push(w.word);
  viewed.add(w.word);
  renderLearnTop();
  renderBrew();
  $("lWord").textContent = w.word;
  $("lWord").classList.remove("veiled-word");
  $("lPhon").textContent = w.phonetic || "";
  $("lDef").textContent = w.definition || "";
  $("lDef").classList.remove("hidden");
  $("lRevealBtn").classList.add("hidden");
  $("lNextBtn").classList.remove("hidden");
  $("lHint").textContent = "可以在故事里听它，也可以接着翻。";
  fillLearnMorph(w.word);
}

/* 翻开后补词根词缀行（FLOW 工具页）；回来时卡已换就丢弃 */
async function fillLearnMorph(word) {
  let r = {};
  try { r = await fetchJSON("/api/lookup?word=" + encodeURIComponent(word)); } catch (_) {}
  const w = curLearn();
  if (lRevealed && w && w.word === word) $("lMorph").innerHTML = morphHTML(r.morph);
}

let cycles = 0;         // 转满几圈了（只做中性展示，不催——产品原则）

function nextLearn() {
  li += 1;
  if (li % pool.length === 0) cycles += 1;   // 转满一圈，顺序不变
  renderLearnTop();
  showLearnCard();
}

/* ---------------- S6 听对话（会话内子页，词源=当前 S2 词池） ---------------- */
const GEN_TIMEOUT = window.MC_GEN_TIMEOUT || 12 * 60;  // 秒；超过按报错处理（测试可缩短）
const SPK_COLORS = { haruka: "var(--spk-haruka)", momo: "var(--spk-momo)",
                     shizuku: "var(--spk-shizuku)", suzu: "var(--spk-suzu)",
                     aoi: "var(--spk-aoi)" };

function getPending() {
  try {
    const p = JSON.parse(localStorage.getItem("mc_home_gen") || "null");
    if (p && p.words && Date.now() / 1000 - p.t0 < GEN_TIMEOUT + 60) return p;
  } catch (_) {}
  return null;
}

function enterListen(genWords) {
  show("vListen");
  $("lsInfo").textContent = "吧台来信 · 为你现做的对话";
  loadTodayDialogues();
  const p = getPending();
  if (p) genWatch(p.words, p.t0);
  else if (genWords && genWords.length) startGen(genWords);
  else genIdle();
}

function genIdle(msg) {
  $("lsGenLine").textContent = msg || "想再来一场：换个场景再来一杯，或回学习页再攒一篮 ☕";
  $("lsGenFill").style.width = "0%";
  $("lsFreeHint").classList.add("hidden");
  $("lsAgainBtn").classList.toggle("hidden", !sceneGroup);
}

async function startGen(words) {
  mclog("gen_start", words.join(","));
  sceneGroup = words;
  const t0 = Date.now() / 1000;
  try { localStorage.setItem("mc_home_gen", JSON.stringify({ words, t0 })); } catch (_) {}
  try {
    const r = await POST("/api/generate", { words });
    if (!r.started) throw Error();
    genWatch(words, t0);
  } catch (error) {
    localStorage.removeItem("mc_home_gen");
    words.forEach(word => inPot.delete(word));
    renderBrew();
    genIdle(error.message || "这段还没开始。可以再试一次，或回窗边听离线招待。");
  }
}

/* 进度条：①写稿(第N/4稿) ②配音 ③上桌；超时/报错说人话 */
/* 出品工序（咖啡流程）：挑豆 → ①磨豆 ②萃取 ③蒸奶 ④调味（=写稿四稿）
   → ⑤拉花（=配音）→ 客人请用（女仆们开始闲聊，一边喝一边听） */
const BREW_STEPS = ["① 磨咖啡豆", "② 萃取浓缩", "③ 蒸奶打泡", "④ 调整风味"];

/* 时间基准估计：本机最近 5 杯的完成时长（localStorage），无历史默认 130 秒。
   工序阶段的百分比映射一档内一动不动、完全不线性——改成条随真实已用时间走，
   工序只作底线；超过平常时长后渐近爬行，未出锅封顶 95%。 */
function genHist() {
  try { return JSON.parse(localStorage.getItem("mc_gen_hist") || "[]"); }
  catch (_) { return []; }
}
function genExpect() {
  const h = genHist();
  return h.length ? h.reduce((a, b) => a + b, 0) / h.length : 130;
}
function genHistPush(sec) {
  const h = genHist();
  h.push(Math.round(sec));
  while (h.length > 5) h.shift();
  try { localStorage.setItem("mc_gen_hist", JSON.stringify(h)); } catch (_) {}
}
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec));
  return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
}

function genWatch(words, t0) {
  sceneGroup = words;
  $("lsAgainBtn").classList.add("hidden");
  $("lsFreeHint").classList.remove("hidden");   // 安心话术：煮着可以回去学
  if (sceneWatch) clearInterval(sceneWatch);
  let list = null, tickN = 0;
  const stop = (clear) => {
    clearInterval(sceneWatch);
    sceneWatch = null;
    $("sceneHint").textContent = "";
    $("lsFreeHint").classList.add("hidden");
    if (clear) { try { localStorage.removeItem("mc_home_gen"); } catch (_) {} }
    renderBrew();
  };
  const tick = async () => {
    const fetched = tickN++ % 5 === 0;   // 秒表每秒走字，锅 5 秒看一次
    if (fetched) {
      try { list = await fetchJSON("/api/dialogues"); } catch (_) {}
    }
    if (!list) return;
    const hit = list.find((d) =>
      d.ts > t0 - 10 && words.every((w) => d.targets.includes(w)));
    const el = Date.now() / 1000 - t0;
    const exp = genExpect();
    const clock = `已 ${fmtDur(el)} · 平常约 ${fmtDur(exp)}`;
    let pct = el < exp ? (el / exp) * 88
                       : 88 + 7 * (1 - Math.exp(-(el - exp) / exp));
    // 只报个数不亮词：盲听产品，挂出来就是自我剧透（2026-09-22 篮子裁决的同一条）
    let line = `☕ 女仆去挑豆了（${words.length} 个词）· ${clock}`;
    if (hit && hit.status === "writing") {
      const m = hit.progress && hit.progress.match(/attempt (\d)/);
      const n = m ? parseInt(m[1], 10) : 1;
      pct = Math.max(pct, 8 + n * 4);
      line = `${BREW_STEPS[n - 1] || BREW_STEPS[3]} · ${clock}`;
    } else if (hit && hit.status === "tts") {
      pct = Math.max(pct, 90);
      line = `⑤ 拉花中 · 就快好了 · ${clock}`;
    } else if (hit && hit.status === "error") {
      mclog("gen_error", hit.error || "");
      $("lsGenLine").textContent = "这段还没煮好。请检查本机 Ollama 和模型，或回窗边点单听离线招待。";
      $("lsGenFill").style.width = "0%";
      $("lsAgainBtn").classList.remove("hidden");
      stop(true);
      return;
    } else if (hit) {  // done
      mclog("gen_done", "#" + hit.id);
      genHistPush(el);                 // 喂给下一杯的时间估计
      stop(true);
      if (view === "vListen") {
        $("lsGenLine").textContent = "☕ 客人请用——女仆们开始闲聊了";
        $("lsGenFill").style.width = "100%";
        $("lsAgainBtn").classList.remove("hidden");
        await loadTodayDialogues();
        lsToggle(hit.id);          // 自动展开，一边喝一边听
      } else {
        toast("☕ 客人请用——那一杯煮好了，点组框去听");
      }
      return;
    }
    pct = Math.min(95, pct);
    if (view === "vListen") {
      $("lsGenLine").textContent = line;
      $("lsGenFill").style.width = pct + "%";
    } else {
      $("sceneHint").textContent = `☕ 灶上：${line}`;
      renderBrew();   // 灶上态挂在按钮上，跟着秒表走
    }
    if (Date.now() / 1000 - t0 > GEN_TIMEOUT) {
      $("lsGenLine").innerHTML =
        `<span class="s1">✗ 超时了——灶可能熄了（Ollama 没开？）· 详见 generate.log</span>`;
      $("lsAgainBtn").classList.remove("hidden");
      stop(true);
    }
  };
  tick();
  sceneWatch = setInterval(tick, 1000);
}

/* 刷新/回来后恢复正在煮的那一场（留在 S2，按钮上提示） */
function resumeScene() {
  const p = getPending();
  if (p) genWatch(p.words, p.t0);
}

/* ---- 今日对话列表（往下追加，一场一条，展开/收起） ---- */
let lsExpanded = null;
let lsBodyEl = null;
let lsCur = null;
let lsTurnIdx = -1, lsPlaying = false, lsPlayed = new Set();

async function loadTodayDialogues() {
  let list;
  try { list = await fetchJSON("/api/dialogues"); } catch (_) { return; }
  const mid = new Date(); mid.setHours(0, 0, 0, 0);
  const today = list.filter((d) => d.ts >= mid.getTime() / 1000 && d.status === "done");
  today.sort((a, b) => a.ts - b.ts);
  const box = $("lsDlgList");
  box.innerHTML = today.length ? "" :
    '<p class="empty">今天还没有对话——上面来一场 ☕</p>';
  lsExpanded = null;
  today.forEach((d) => {
    const el = document.createElement("div");
    el.className = "ditem";
    el.dataset.id = d.id;
    el.innerHTML =
      `<div class="d-top"><span class="ls-arrow">▸</span> <b>#${d.id}</b> · ` +
      `${d.n_turns} 轮 · ${cafeEscape(d.characters.join("、"))}</div>` +
      `<div class="d-scene">${cafeEscape(d.scene)}</div>` +   // 不挂目标词：盲听不剧透（FLOW 全局）
      `<div class="ls-body hidden"></div>`;
    el.addEventListener("click", (e) => {
      if (e.target.closest(".ls-body") || e.target.closest("button")) return;
      lsToggle(d.id);
    });
    box.appendChild(el);
  });
}

async function lsToggle(id) {
  const items = [...$("lsDlgList").children];
  const el = items.find((x) => parseInt(x.dataset.id, 10) === id);
  if (!el) return;
  if (lsExpanded !== null) {   // 收起旧的（含自己：再点一次=收起）
    const prev = items.find((x) => parseInt(x.dataset.id, 10) === lsExpanded);
    if (prev) {
      prev.querySelector(".ls-body").classList.add("hidden");
      prev.querySelector(".ls-arrow").textContent = "▸";
    }
    lsPlaying = false;
    if (audioEl) audioEl.pause();
    if (lsExpanded === id) { lsExpanded = null; return; }
  }
  lsExpanded = id;
  el.querySelector(".ls-arrow").textContent = "▾";
  lsBodyEl = el.querySelector(".ls-body");
  lsBodyEl.classList.remove("hidden");
  lsBodyEl.innerHTML = '<p class="hint-line">端上来了…</p>';
  lsCur = await fetchJSON("/api/dialogue/" + id);
  lsTurnIdx = -1; lsPlaying = false; lsPlayed = new Set();
  lsBodyEl.innerHTML =
    `<div class="player-controls" style="border-bottom:none;padding-left:0;padding-right:0;">` +
    `<button class="mk ls-play">▶ 播放</button>` +
    `<button class="mk small ls-prev">◂ 上一轮</button>` +
    `<button class="mk small ls-next">下一轮 ▸</button>` +
    `<span class="hint-line ls-prog"></span></div>` +
    `<div class="turn-list ls-turns" style="padding-left:0;"></div>`;
  lsBodyEl.querySelector(".ls-play").addEventListener("click", lsTogglePlay);
  lsBodyEl.querySelector(".ls-prev").addEventListener("click",
    () => lsPlayTurn(Math.max(0, lsTurnIdx - 1)));
  lsBodyEl.querySelector(".ls-next").addEventListener("click",
    () => lsPlayTurn(Math.min(lsCur.turns.length - 1, lsTurnIdx + 1)));
  lsRenderTurns();
}

function lsMatchTarget(tok) {
  const lw = tok.toLowerCase();
  const t = lsCur.targets.find((x) => {
    const w = x.word.toLowerCase();
    return lw === w || (lw.startsWith(w) && lw.length - w.length <= 3) ||
           (w.startsWith(lw) && w.length - lw.length <= 1);
  });
  return t ? t.word : null;
}

function lsHl(text) { return cafeSpeech(text, lsCur.targets); }

function lsRenderTurns() {
  if (!lsBodyEl || !lsCur) return;
  const box = lsBodyEl.querySelector(".ls-turns");
  box.innerHTML = "";
  lsBodyEl.querySelector(".ls-prog").textContent =
    `${lsPlayed.size}/${lsCur.turns.length} 轮`;
  lsBodyEl.querySelector(".ls-play").textContent = !lsCur.files.length ? "文字故事 · 点句子阅读" : lsPlaying ? "⏸ 暂停" : "▶ 播放";
  lsBodyEl.querySelector(".ls-play").disabled = !lsCur.files.length;
  lsCur.turns.forEach((t, i) => {
    const div = document.createElement("div");
    div.className = "turn" + (i === lsTurnIdx ? " current" : "");
    const show = !lsCur.files.length || lsPlayed.has(i);
    const color = SPK_COLORS[t.speaker.toLowerCase()] || "var(--muted-2)";
    div.innerHTML =
      `<span class="spk" style="color:${color}">${artAvatar(t.speaker)}${cafeEscape(t.speaker)}</span>` +
      (show ? `<span class="txt">${lsHl(t.text)}</span>`
            : `<span class="txt veiled">●●●</span>`);
    div.addEventListener("click", (e) => {
      if (e.target.closest(".wclick")) return;
      lsPlayTurn(i);
    });
    box.appendChild(div);
  });
  box.querySelectorAll(".wclick").forEach((s) =>
    s.addEventListener("click", (e) => {
      e.stopPropagation();
      showWordCard(s.dataset.word);
    }));
}

function lsPlayTurn(i) {
  if (!lsCur || i < 0 || i >= lsCur.turns.length) return;
  lsTurnIdx = i;
  lsPlayed.add(i);
  lsPlaying = true;
  if (audioEl) audioEl.pause();
  const f = lsCur.files[i];
  if (!f) { lsPlaying = false; lsRenderTurns(); return; }
  audioEl = new Audio(`/dialogue_audio/${lsCur.id}/${f}`);
  audioEl.onended = lsOnEnd;
  audioEl.play().catch(() => {});
  lsRenderTurns();
}

function lsOnEnd() {
  if (!lsPlaying) return;
  if (lsTurnIdx + 1 < lsCur.turns.length) lsPlayTurn(lsTurnIdx + 1);
  else { lsPlaying = false; lsRenderTurns(); }
}

function lsTogglePlay() {
  if (lsPlaying) {
    lsPlaying = false;
    if (audioEl) audioEl.pause();
    lsRenderTurns();
  } else {
    lsPlayTurn(lsTurnIdx < 0 ? 0 : lsTurnIdx);
  }
}

/* ---- 释义卡（点词自动暂停，关闭续播） ---- */
let wcPaused = false;

async function showWordCard(word) {
  wcPaused = lsPlaying;
  if (lsPlaying) { lsPlaying = false; if (audioEl) audioEl.pause(); lsRenderTurns(); }
  $("wcWord").textContent = word;
  $("wcPhon").textContent = "";
  $("wcDef").textContent = "…";
  $("wcMorph").innerHTML = "";
  $("wcAdd").classList.add("hidden");
  openCafeDialog("wordCard", "wcClose");
  const r = await fetchJSON("/api/lookup?word=" + encodeURIComponent(word));
  $("wcPhon").textContent = r.phonetic || "";
  $("wcDef").textContent = r.definition || "词典里查不到这个词";
  $("wcMorph").innerHTML = morphHTML(r.morph);
  $("wcAdd").classList.toggle("hidden", !r.definition || r.in_wordbook);
  $("wcAdd").textContent = "＋ 加入生词本";
  $("wcAdd").dataset.word = word;
}
$("wcClose").addEventListener("click", () => {
  closeCafeDialog("wordCard");
  if (wcPaused && lsCur) lsPlayTurn(Math.max(0, lsTurnIdx));
});
$("wcPlay").addEventListener("click", () => {
  const a = new Audio("/audio/" + encodeURIComponent($("wcWord").textContent));
  a.play().catch(() => {});
});
$("wcAdd").addEventListener("click", async (e) => {
  const w = e.currentTarget.dataset.word;
  const r = await POST("/api/wordbook_add", { word: w });
  e.currentTarget.textContent = r.ok ? "✓ 已加入" : (r.error || "加入失败");
});

/* ---------------- 考试（两键自评，主动权在用户） ---------------- */
function enterExam() {
  exQueue = shuffle(pool.filter(w => viewed.has(w.word)));
  if (!exQueue.length) return;
  exIdx = 0;
  exPassed = 0;
  exFailed = 0;
  show("vExam");
  showExamCard();
}

function curExam() { return exQueue[exIdx]; }

function showExamCard() {
  if (exIdx >= exQueue.length) { examDone(); return; }
  const w = curExam();
  exPhase = "listen";
  $("examProgress").innerHTML =
    `回想片刻 · 第 ${exIdx + 1} 个，共 ${exQueue.length} 个`;
  $("exListen").classList.remove("hidden");
  $("exAnswer").classList.add("hidden");
  $("exJudge").classList.remove("hidden");
  $("exFinal").classList.add("hidden");
  if (w.has_audio) {
    $("exPlayBtn").classList.remove("hidden");
    $("exWordPreview").classList.add("hidden");
    playWord(w);
  } else {
    $("exPlayBtn").classList.add("hidden");
    $("exWordPreview").textContent = w.word;
    $("exWordPreview").classList.remove("hidden");
  }
}

function examJudge() {
  if (exPhase !== "listen") return;
  exPhase = "final";

  const w = curExam();
  $("exListen").classList.add("hidden");
  $("exAnswer").classList.remove("hidden");
  $("exJudge").classList.add("hidden");
  $("exFinal").classList.remove("hidden");
  $("exWord").textContent = w.word;
  $("exPhon").textContent = w.phonetic || "";
  $("exDef").textContent = w.definition || "";
}

async function examFinalize(pass) {
  if (exPhase !== "final" || examSaving) return;
  const w = curExam();
  examSaving = true;
  ["examQuitBtn", "exYes2", "exNo2"].forEach(id => $(id).disabled = true);
  try {
    const r = await POST(pass ? "/api/word_pass" : "/api/word_fail", { word: w.word });
    if (!r.ok) throw Error();
    exIdx++;
    if (pass) { exPassed++; passed.add(w.word); rebuildPool(); }
    else exFailed++;
    mclog("exam", w.word + (pass ? " recalled" : " revisit"));
    showExamCard();
  } catch (_) { toast("这次回想还没保存，请再按一次。"); }
  finally {
    examSaving = false;
    ["examQuitBtn", "exYes2", "exNo2"].forEach(id => $(id).disabled = false);
  }
}

function examDone() {
  renderLearnTop();
  if (!pool.length) { renderDone(); return; }   // 全过 -> S5a
  $("exDoneTitle").textContent = "这一段，先到这里 ☕";
  $("exDoneStats").innerHTML =
    `刚才回想了 ${exIdx} 个词。下次来，再换个故事。`;
  show("vExamDone");
}

/* ---------------- S5a 这一份全拿下 ---------------- */
function renderDone() {
  $("doneLine").innerHTML =
    `这次和 ${sessionTotal} 个词见了面。`;
  show("vDone");
}

/* ---------------- 事件 ---------------- */
$("sitBtn").addEventListener("click", () => show("vSeat"));
async function takeSeat() {
  const result = await POST("/api/visit", {});
  if (!result.ok) throw Error();
  history.replaceState(null, "", "/");
  await loadSession();
}
$("starterBtn").addEventListener("click", async () => {
  try { await takeSeat(); pool.length ? enterLearn() : show("vEmpty"); }
  catch (_) { toast("没能打开词卡，请再试一次。"); }
});
$("orderForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const words = [...new Set($("orderWords").value.trim().toLowerCase().split(/[,，;；\n]+/).map(s => s.trim()).filter(Boolean))];
  if (!words.length || words.length > 5 || words.some(w => !/^[a-z]+(?:[ '-][a-z]+){0,3}$/.test(w))) {
    $("orderMsg").textContent = "写 1–5 个英文词或短语，词与词用逗号隔开。"; return;
  }
  if (storySetupState && !storySetupState.ready) { openStorySetup(); return; }
  if (getPending()) { $("orderMsg").textContent = "上一段故事还在准备，稍后再点这一段。"; return; }
  const button = e.currentTarget.querySelector("button");
  button.disabled = true;
  try { await takeSeat(); enterListen(words); }
  catch (_) { $("orderMsg").textContent = "没有连到店内服务，请再试一次。"; }
  finally { button.disabled = false; }
});
$("goProbeBtn").addEventListener("click", () => location.href = "/calibrate?probe=1");
$("lPlayBtn").addEventListener("click", (e) => { e.currentTarget.blur(); playWord(curLearn()); });
$("lRevealBtn").addEventListener("click", (e) => { e.currentTarget.blur(); revealLearn(); });
$("lNextBtn").addEventListener("click", (e) => { e.currentTarget.blur(); nextLearn(); });
$("introStartBtn").addEventListener("click", enterLearn);
$("brewBtn").addEventListener("click", () => {
  if (getPending()) { enterListen(null); return; }   // 灶上：进 S6 看进度
  const q = brewQueue();
  if (!q.length) return;
  q.forEach((w) => inPot.add(w));
  mclog("brew", q.join(","));
  enterListen(q);
});
$("lsBackBtn").addEventListener("click", enterLearn);
$("lsExamBtn").addEventListener("click", enterExam);
$("lsAgainBtn").addEventListener("click", () => sceneGroup && startGen(sceneGroup));
$("examBtn").addEventListener("click", enterExam);
$("examQuitBtn").addEventListener("click", enterLearn);
$("backToLearnBtn").addEventListener("click", enterLearn);
$("moreBtn").addEventListener("click", async () => {
  // 再来一份：和重新打开软件完全等效（考过的自然不在了，新词接着上）
  await loadSession();
  if (!pool.length) { show("vEmpty"); return; }
  toast(`新一份上桌：${pool.length} 个词 ☕`);
  enterLearn();
});
$("exPlayBtn").addEventListener("click", (e) => { e.currentTarget.blur(); playWord(curExam()); });
$("exYes").addEventListener("click", (e) => { e.currentTarget.blur(); examJudge(true); });

$("exYes2").addEventListener("click", (e) => { e.currentTarget.blur(); examFinalize(true); });
$("exNo2").addEventListener("click", (e) => { e.currentTarget.blur(); examFinalize(false); });

document.addEventListener("keydown", (e) => {
  if (!cafeShortcut(e)) return;
  if (view === "vLearn") {
    if (e.key === " ") { e.preventDefault(); lRevealed ? nextLearn() : revealLearn(); }
    if (e.key === "k" || e.key === "K") playWord(curLearn());
  } else if (view === "vExam") {
    if (e.key === " ") {
      e.preventDefault();
      if (exPhase === "listen") examJudge();
    }
    if (e.key.toLowerCase() === "f") examFinalize(true);
    if (e.key.toLowerCase() === "j") examFinalize(false);
    if (e.key === "k" || e.key === "K") playWord(curExam());
  } else if (view === "vListen") {
    if (e.key === " " && lsCur && lsExpanded !== null) {
      e.preventDefault();
      lsTogglePlay();
    }
  }
});

/* ---------------- 设置 ---------------- */
$("cfgBtn").addEventListener("click", async () => {
  const c = await fetchJSON("/api/config");
  $("quotaInput").value = c.new_quota;
  try {
    const v = await fetchJSON("/api/vocab_estimate");
    $("cfgVocab").innerHTML = v.unmeasured_blocks === 0 && v.hearing_samples > 0
      ? `当前测定：听得出 ≈ <b>${fmtN(v.listening)}</b> · 看得懂 ≈ <b>${fmtN(v.reading)}</b> 词`
      : "";
  } catch (_) {}
  openCafeDialog("cfgModal", "cfgClose");
});
$("cfgClose").addEventListener("click", () => closeCafeDialog("cfgModal"));
$("quotaSave").addEventListener("click", async () => {
  const q = parseInt($("quotaInput").value, 10);
  const r = await POST("/api/config", { new_quota: q });
  toast(r.ok ? `每份新词已改为 ${q}` : (r.error || "保存失败"));
});
boot();
