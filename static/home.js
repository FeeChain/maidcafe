/* maidcafe home — 产品主流程状态机。
 * 新客人 → 测词汇量；老客人 → 今日计划：
 * 词卡随机循环学习 ⇄ 按需 5 词一场对话 ⇄ 用户主动考试（两键自评）
 * → 全过=完成；点「今天到这」后没考过的词照旧到期，明天回炉。 */

const $ = (id) => document.getElementById(id);
async function fetchJSON(url, opts) { const r = await fetch(url, opts); return r.json(); }
const POST = (url, body) => fetchJSON(url, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});
const fmtN = (x) => x.toLocaleString("zh-CN");

let view = "";           // vNew | vEmpty | vLearn | vExam | vExamDone | vDone
let sessionWords = [];   // 本次会话的一份词（/api/session 现抓，零落库）
let pool = [];           // 还没考过的词（学习循环用，乱序）
let li = 0;              // 学习卡游标
let lRevealed = false;
let audioEl = null;
let sceneGroup = null;   // 最近一场对话的 5 词
let sceneWatch = null;
let exQueue = [];        // 本轮考试队列
let exIdx = 0;
let exPhase = "listen";
let exHeard = false;
let exPassed = 0; let exFailed = 0;

function show(v) {
  ["vNew", "vEmpty", "vLearn", "vListen", "vExam", "vExamDone", "vDone"].forEach((id) =>
    $(id).classList.toggle("hidden", id !== v));
  view = v;
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
 * 每次打开现抓一份（到期复习全上 + 新词 20），背完就是背完；
 * 唯一落库的是「考试通过」（SRS 爬梯即实时记录），其余什么都不记。 */
async function boot() {
  const s = await fetchJSON("/api/home_status");
  resumeScene();   // 煮着的对话在任何视图都继续盯（不在学习页就 toast 通知）
  if (!s.calibrated) { show("vNew"); return; }
  await loadSession();
  if (!pool.length) { show("vEmpty"); return; }  // 生词池和复习都空：去攒词
  enterLearn();                                  // 其余一律直落 S2
}

async function loadSession() {
  const r = await fetchJSON("/api/session");
  sessionWords = r.words;
  pool = shuffle(sessionWords.slice());
  li = 0;
  cycles = 0;
}

/* ---------------- 学习循环 ---------------- */
function enterLearn() {
  if (!pool.length) { renderDone(); return; }
  show("vLearn");
  renderLearnTop();
  showLearnCard();
}

function renderLearnTop() {
  const done = sessionWords.length - pool.length;
  $("learnProgress").innerHTML =
    `这一份 <b>${done}</b>/${sessionWords.length} 已拿下 · 在学 ${pool.length} 个`;
  $("examBtn").textContent = `✍ 我准备好了，考试（${pool.length} 词）`;
}

function curLearn() { return pool[li % pool.length]; }

function showLearnCard() {
  const w = curLearn();
  if (!w) return;
  lRevealed = false;
  $("newTag").classList.toggle("hidden", !w.is_new);
  $("lWord").textContent = "· · ·";
  $("lWord").classList.add("veiled-word");
  $("lPhon").textContent = "";
  $("lDef").classList.add("hidden");
  $("lRevealBtn").classList.remove("hidden");
  $("lNextBtn").classList.add("hidden");
  playWord(w);
}

function revealLearn() {
  const w = curLearn();
  lRevealed = true;
  $("lWord").textContent = w.word;
  $("lWord").classList.remove("veiled-word");
  $("lPhon").textContent = w.phonetic || "";
  $("lDef").textContent = w.definition || "";
  $("lDef").classList.remove("hidden");
  $("lRevealBtn").classList.add("hidden");
  $("lNextBtn").classList.remove("hidden");
}

let cycles = 0;         // 转满几圈了（只做中性展示，不催——产品原则）

function nextLearn() {
  li += 1;
  if (li % pool.length === 0) {
    shuffle(pool);       // 每转完一圈重新洗
    cycles += 1;
  }
  renderLearnTop();
  showLearnCard();
}

/* ---------------- S6 听对话（会话内子页，词源=当前 S2 词池） ---------------- */
function nextFive() {
  const out = [];
  for (let k = 0; k < Math.min(5, pool.length); k++) {
    out.push(pool[(li + k) % pool.length].word);
  }
  return out;
}

const GEN_TIMEOUT = 12 * 60;  // 秒；超过按报错处理
const SCENE_BTN_IDLE = "☕ 给接下来 5 个词来一场对话";
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

function enterListen(gen) {
  show("vListen");
  $("lsInfo").innerHTML = `词源：当前在学的 <b>${pool.length}</b> 个词`;
  loadTodayDialogues();
  const p = getPending();
  if (p) genWatch(p.words, p.t0);
  else if (gen && pool.length) startGen(nextFive());
  else genIdle("想来一场？");
}

function genIdle(msg) {
  $("lsGenLine").textContent = msg || "想再来一场？";
  $("lsGenFill").style.width = "0%";
  $("lsAgainBtn").classList.toggle("hidden", !sceneGroup);
  $("lsNext5Btn").classList.toggle("hidden", !pool.length);
}

async function startGen(words) {
  sceneGroup = words;
  const t0 = Date.now() / 1000;
  try { localStorage.setItem("mc_home_gen", JSON.stringify({ words, t0 })); } catch (_) {}
  await POST("/api/generate", { words });
  genWatch(words, t0);
}

/* 进度条：①写稿(第N/4稿) ②配音 ③上桌；超时/报错说人话 */
function genWatch(words, t0) {
  sceneGroup = words;
  $("lsAgainBtn").classList.add("hidden");
  $("lsNext5Btn").classList.add("hidden");
  if (sceneWatch) clearInterval(sceneWatch);
  const stop = (clear) => {
    clearInterval(sceneWatch);
    sceneWatch = null;
    $("sceneBtn").textContent = SCENE_BTN_IDLE;
    if (clear) { try { localStorage.removeItem("mc_home_gen"); } catch (_) {} }
  };
  const tick = async () => {
    const mins = Math.max(1, Math.round((Date.now() / 1000 - t0) / 60));
    let list;
    try { list = await fetchJSON("/api/dialogues"); } catch (_) { return; }
    const hit = list.find((d) =>
      d.ts > t0 - 10 && words.every((w) => d.targets.includes(w)));
    let pct = 5, line = `☕ 灶已点火（${words.join(", ")}）…`;
    if (hit && hit.status === "writing") {
      const m = hit.progress && hit.progress.match(/attempt (\d)/);
      const n = m ? parseInt(m[1], 10) : 1;
      pct = 10 + n * 18;
      line = `① 女仆们在写稿 第 ${n}/4 稿 · 已 ${mins} 分钟`;
    } else if (hit && hit.status === "tts") {
      pct = 90; line = "② 配音中 · 就快好了";
    } else if (hit && hit.status === "error") {
      $("lsGenLine").innerHTML =
        `<span class="s1">✗ 这一场翻车了：${hit.error || "未知原因"} · 详见 generate.log</span>`;
      $("lsGenFill").style.width = "0%";
      stop(true);
      $("lsAgainBtn").classList.remove("hidden");
      $("lsNext5Btn").classList.toggle("hidden", !pool.length);
      return;
    } else if (hit) {  // done
      stop(true);
      if (view === "vListen") {
        $("lsGenLine").textContent = "③ 上桌！想再来：";
        $("lsGenFill").style.width = "100%";
        $("lsAgainBtn").classList.remove("hidden");
        $("lsNext5Btn").classList.toggle("hidden", !pool.length);
        await loadTodayDialogues();
        lsToggle(hit.id);          // 自动展开新一场
      } else {
        toast("那场对话煮好了 ☕ 点「听对话」开吃");
        $("sceneBtn").textContent = "☕ 听对话（有一场刚出锅）";
      }
      return;
    }
    if (view === "vListen") {
      $("lsGenLine").textContent = line;
      $("lsGenFill").style.width = pct + "%";
    } else {
      $("sceneBtn").textContent = "☕ 听对话（灶上煮着…）";
    }
    if (Date.now() / 1000 - t0 > GEN_TIMEOUT) {
      $("lsGenLine").innerHTML =
        `<span class="s1">✗ 超时了——灶可能熄了（Ollama 没开？）· 详见 generate.log</span>`;
      stop(true);
      $("lsAgainBtn").classList.remove("hidden");
      $("lsNext5Btn").classList.toggle("hidden", !pool.length);
    }
  };
  tick();
  sceneWatch = setInterval(tick, 5000);
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
      `${d.n_turns} 轮 · ${d.characters.join("、")}</div>` +
      `<div class="d-scene">${d.scene}</div>` +
      `<div class="d-targets">${d.targets.map((x) =>
        `<span class="chip">${x}</span>`).join("")}</div>` +
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

function lsHl(text) {
  return text.replace(/[A-Za-z][A-Za-z']*/g, (m) => {
    if (m.length <= 2) return m;
    const tg = lsMatchTarget(m);
    return `<span class="${tg ? "wclick tword" : "wclick"}" ` +
           `data-word="${(tg || m).toLowerCase()}">${m}</span>`;
  });
}

function lsRenderTurns() {
  if (!lsBodyEl || !lsCur) return;
  const box = lsBodyEl.querySelector(".ls-turns");
  box.innerHTML = "";
  lsBodyEl.querySelector(".ls-prog").textContent =
    `${lsPlayed.size}/${lsCur.turns.length} 轮`;
  lsBodyEl.querySelector(".ls-play").textContent = lsPlaying ? "⏸ 暂停" : "▶ 播放";
  lsCur.turns.forEach((t, i) => {
    const div = document.createElement("div");
    div.className = "turn" + (i === lsTurnIdx ? " current" : "");
    const show = lsPlayed.has(i);
    const color = SPK_COLORS[t.speaker.toLowerCase()] || "var(--muted-2)";
    div.innerHTML =
      `<span class="spk" style="color:${color}">${artAvatar(t.speaker)}${t.speaker}</span>` +
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
  if (!f) { lsOnEnd(); return; }
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
  $("wcAdd").classList.add("hidden");
  $("wordCard").classList.remove("hidden");
  const r = await fetchJSON("/api/lookup?word=" + encodeURIComponent(word));
  $("wcPhon").textContent = r.phonetic || "";
  $("wcDef").textContent = r.definition || "词典里查不到这个词";
  $("wcAdd").classList.toggle("hidden", !r.definition || r.in_wordbook);
  $("wcAdd").textContent = "＋ 加入生词本";
  $("wcAdd").dataset.word = word;
}
$("wcClose").addEventListener("click", () => {
  $("wordCard").classList.add("hidden");
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
  exQueue = shuffle(pool.slice());
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
    `考试 <b>${exIdx}</b>/${exQueue.length} · 过 ${exPassed} · 挂 ${exFailed}`;
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

function examJudge(didHear) {
  if (exPhase !== "listen") return;
  exPhase = "final";
  exHeard = didHear;
  const w = curExam();
  $("exListen").classList.add("hidden");
  $("exAnswer").classList.remove("hidden");
  $("exJudge").classList.add("hidden");
  $("exFinal").classList.remove("hidden");
  $("exWord").textContent = w.word;
  $("exPhon").textContent = w.phonetic || "";
  $("exDef").textContent = w.definition || "";
}

async function examFinalize(canRead) {
  if (exPhase !== "final") return;
  const w = curExam();
  const pass = exHeard && canRead;
  exIdx += 1;
  if (pass) {
    exPassed += 1;
    pool = pool.filter((x) => x.word !== w.word);
    POST("/api/word_pass", { word: w.word });
  } else {
    exFailed += 1;
  }
  showExamCard();
}

function examDone() {
  renderLearnTop();
  if (!pool.length) { renderDone(); return; }   // 全过 -> S5a
  $("exDoneTitle").textContent = exFailed ? "差一点点 ☕" : "这一轮全过 🎉";
  $("exDoneStats").innerHTML =
    `通过 <b>${exPassed}</b> · 还剩 <b>${pool.length}</b> 个没拿下`;
  show("vExamDone");
}

/* ---------------- S5a 这一份全拿下 ---------------- */
function renderDone() {
  $("doneLine").innerHTML =
    `${sessionWords.length} 个词全部通过考试`;
  show("vDone");
}

/* ---------------- 事件 ---------------- */
$("goProbeBtn").addEventListener("click", () => location.href = "/calibrate?probe=1");
$("lPlayBtn").addEventListener("click", (e) => { e.currentTarget.blur(); playWord(curLearn()); });
$("lRevealBtn").addEventListener("click", (e) => { e.currentTarget.blur(); revealLearn(); });
$("lNextBtn").addEventListener("click", (e) => { e.currentTarget.blur(); nextLearn(); });
$("sceneBtn").addEventListener("click", () => enterListen(true));
$("lsBackBtn").addEventListener("click", enterLearn);
$("lsExamBtn").addEventListener("click", enterExam);
$("lsAgainBtn").addEventListener("click", () => sceneGroup && startGen(sceneGroup));
$("lsNext5Btn").addEventListener("click", () => pool.length && startGen(nextFive()));
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
$("exNo").addEventListener("click", (e) => { e.currentTarget.blur(); examJudge(false); });
$("exYes2").addEventListener("click", (e) => { e.currentTarget.blur(); examFinalize(true); });
$("exNo2").addEventListener("click", (e) => { e.currentTarget.blur(); examFinalize(false); });

document.addEventListener("keydown", (e) => {
  if (e.repeat) return;
  if (e.target.tagName === "INPUT") return;
  if (view === "vLearn") {
    if (e.key === " ") { e.preventDefault(); lRevealed ? nextLearn() : revealLearn(); }
    if (e.key === "k" || e.key === "K") playWord(curLearn());
  } else if (view === "vExam") {
    if (e.key === " ") {
      e.preventDefault();
      exPhase === "listen" ? examJudge(true) : examFinalize(true);
    }
    if (e.key === "j" || e.key === "J") {
      exPhase === "listen" ? examJudge(false) : examFinalize(false);
    }
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
    $("cfgVocab").innerHTML = v.unmeasured_blocks === 0 && v.sampled > 0
      ? `当前测定：听得出 ≈ <b>${fmtN(v.listening)}</b> · 看得懂 ≈ <b>${fmtN(v.reading)}</b> 词`
      : "";
  } catch (_) {}
  $("cfgModal").classList.remove("hidden");
});
$("cfgClose").addEventListener("click", () => $("cfgModal").classList.add("hidden"));
$("quotaSave").addEventListener("click", async () => {
  const q = parseInt($("quotaInput").value, 10);
  const r = await POST("/api/config", { new_quota: q });
  toast(r.ok ? `每份新词已改为 ${q}` : (r.error || "保存失败"));
});
boot();
