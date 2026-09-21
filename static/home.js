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
  ["vNew", "vEmpty", "vLearn", "vExam", "vExamDone", "vDone"].forEach((id) =>
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

/* ---------------- 场景对话（5 词一场） ---------------- */
function nextFive() {
  const out = [];
  for (let k = 0; k < Math.min(5, pool.length); k++) {
    out.push(pool[(li + k) % pool.length].word);
  }
  return out;
}

const GEN_TIMEOUT = 12 * 60;  // 秒；超过按报错处理

async function requestScene(words) {
  sceneGroup = words;
  const t0 = Date.now() / 1000;
  try { localStorage.setItem("mc_home_gen", JSON.stringify({ words, t0 })); } catch (_) {}
  await POST("/api/generate", { words });
  watchScene(words, t0);
}

/* 分步进度：①写稿(可能修 4 稿) ②配音 ③上桌；超时/报错都说人话 */
function watchScene(words, t0) {
  sceneGroup = words;
  $("sceneBtn").disabled = true;
  $("sceneAgainBtn").classList.add("hidden");
  $("sceneGoBtn").classList.add("hidden");
  if (sceneWatch) clearInterval(sceneWatch);
  const stop = (clearPending) => {
    clearInterval(sceneWatch);
    sceneWatch = null;
    $("sceneBtn").disabled = false;
    if (clearPending) { try { localStorage.removeItem("mc_home_gen"); } catch (_) {} }
  };
  const tick = async () => {
    const mins = Math.max(1, Math.round((Date.now() / 1000 - t0) / 60));
    let list;
    try { list = await fetchJSON("/api/dialogues"); } catch (_) { return; }
    const hit = list.find((d) =>
      d.ts > t0 - 10 && words.every((w) => d.targets.includes(w)));
    if (!hit) {
      $("sceneStatus").textContent = `☕ 灶已点火（${words.join(", ")}）…`;
    } else if (hit.status === "writing") {
      const att = hit.progress && hit.progress.startsWith("attempt")
        ? `第 ${hit.progress.slice(8)} 稿` : "";
      $("sceneStatus").textContent =
        `① 女仆们在写稿 ${att} · 已 ${mins} 分钟（写完还要配音）`;
    } else if (hit.status === "tts") {
      $("sceneStatus").textContent = `② 配音中 · 已 ${mins} 分钟，就快好了`;
    } else if (hit.status === "error") {
      $("sceneStatus").innerHTML =
        `<span class="s1">✗ 这一场翻车了：${hit.error || "未知原因"} · 详见 generate.log</span>`;
      $("sceneAgainBtn").classList.remove("hidden");
      stop(true);
      return;
    } else {  // done
      $("sceneStatus").textContent = "③ 上桌！";
      $("sceneGoBtn").href = `/listen#dialogue=${hit.id}`;
      $("sceneGoBtn").classList.remove("hidden");
      $("sceneAgainBtn").classList.remove("hidden");
      if (view !== "vLearn") toast("那场对话煮好了 ☕ 去对话史就能听");
      stop(true);
      return;
    }
    if (Date.now() / 1000 - t0 > GEN_TIMEOUT) {
      $("sceneStatus").innerHTML =
        `<span class="s1">✗ 超时了——灶可能熄了（Ollama 没开？）· 详见 generate.log</span>`;
      $("sceneAgainBtn").classList.remove("hidden");
      stop(true);
    }
  };
  tick();
  sceneWatch = setInterval(tick, 5000);
}

/* 刷新/回来后恢复正在煮的那一场 */
function resumeScene() {
  let p = null;
  try { p = JSON.parse(localStorage.getItem("mc_home_gen") || "null"); } catch (_) {}
  if (p && p.words && Date.now() / 1000 - p.t0 < GEN_TIMEOUT + 60) {
    watchScene(p.words, p.t0);
  }
}

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
$("sceneBtn").addEventListener("click", () => requestScene(nextFive()));
$("sceneAgainBtn").addEventListener("click", () => sceneGroup && requestScene(sceneGroup));
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
