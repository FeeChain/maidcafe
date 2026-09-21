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

let view = "";           // vNew | vReady | vLearn | vExam | vExamDone | vDone
let plan = null;         // /api/plan 返回
let pool = [];           // 未通过的词（学习循环用，乱序）
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
  ["vNew", "vReady", "vLearn", "vExam", "vExamDone", "vDone"].forEach((id) =>
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
  audioEl.play().catch(() => {});
}

/* ---------------- 主状态机 ---------------- */
async function boot() {
  const s = await fetchJSON("/api/home_status");
  if (!s.calibrated) { show("vNew"); return; }
  if (s.plan && (s.plan.finished || s.plan.done >= s.plan.total) && s.plan.total > 0) {
    await loadPlan();
    renderDone();
    return;
  }
  if (s.plan) {         // 进行中：直接回到学习
    await loadPlan();
    enterLearn();
    return;
  }
  // 今日未开始
  $("menuLine").innerHTML =
    `今天的菜单：到期复习 <b>${s.due}</b> · 新词 <b>${s.new_today}</b>` +
    `<span class="hint-line">（配额 ${s.new_quota}，设置里可调）</span>`;
  $("readyHint").innerHTML =
    s.due + s.new_today === 0
      ? `词池空了——去<a href="/calibrate">校准工具</a>过几块词攒生词 ☕`
      : (s.backlog < s.new_quota
          ? `生词池只剩 ${s.backlog} 个新词，想多学去<a href="/calibrate">校准工具</a>再过几块`
          : "");
  show("vReady");
}

async function loadPlan() {
  plan = await fetchJSON("/api/plan");
  pool = shuffle(plan.words.filter((w) => !w.passed));
  li = 0;
}

/* ---------------- 学习循环 ---------------- */
function enterLearn() {
  if (!pool.length) { renderDone(); return; }
  show("vLearn");
  renderLearnTop();
  showLearnCard();
}

function renderLearnTop() {
  const done = plan.words.length - pool.length;
  $("learnProgress").innerHTML =
    `今日 <b>${done}</b>/${plan.words.length} 已过 · 在学 ${pool.length} 个` +
    (cycles ? ` · 已转 ${cycles} 圈` : ` · 本圈 ${(li % pool.length) + 1}/${pool.length}`);
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

let cycles = 0;         // 转满几圈了（考试轻推用）
let nudged = false;

function nextLearn() {
  li += 1;
  if (li % pool.length === 0) {
    shuffle(pool);       // 每转完一圈重新洗
    cycles += 1;
    // 行业教训：自主考试的拖延风险 -> 转满一圈后轻推，不强制
    if (cycles >= 1 && !nudged) {
      nudged = true;
      $("examBtn").classList.add("pulse");
      toast(`这 ${pool.length} 个词你已经转满一圈了——考考看？主动权在你 ☕`);
    }
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

async function requestScene(words) {
  sceneGroup = words;
  $("sceneBtn").disabled = true;
  $("sceneAgainBtn").classList.add("hidden");
  $("sceneGoBtn").classList.add("hidden");
  $("sceneStatus").textContent =
    `灶上煮着（${words.join(", ")}）… 约 1-3 分钟，这边可以继续转卡片 ☕`;
  const t0 = Date.now() / 1000;
  await POST("/api/generate", { words });
  if (sceneWatch) clearInterval(sceneWatch);
  sceneWatch = setInterval(async () => {
    const list = await fetchJSON("/api/dialogues");
    const hit = list.find((d) =>
      d.ts > t0 - 5 && d.status !== "generating" &&
      words.every((w) => d.targets.includes(w)));
    if (hit) {
      clearInterval(sceneWatch);
      sceneWatch = null;
      $("sceneBtn").disabled = false;
      $("sceneAgainBtn").classList.remove("hidden");
      $("sceneStatus").textContent = "这一场煮好了：";
      $("sceneGoBtn").href = `/listen#dialogue=${hit.id}`;
      $("sceneGoBtn").classList.remove("hidden");
    }
  }, 5000);
}

/* ---------------- 考试（两键自评，主动权在用户） ---------------- */
function enterExam() {
  $("examBtn").classList.remove("pulse");
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
    POST("/api/plan_pass", { word: w.word });
  } else {
    exFailed += 1;
  }
  showExamCard();
}

function examDone() {
  renderLearnTop();
  if (!pool.length) {
    POST("/api/plan_end", {});
    renderDone();
    return;
  }
  $("exDoneTitle").textContent = exFailed ? "差一点点 ☕" : "这一轮全过 🎉";
  $("exDoneStats").innerHTML =
    `通过 <b>${exPassed}</b> · 还剩 <b>${pool.length}</b> 个没拿下`;
  show("vExamDone");
}

/* ---------------- 完成 ---------------- */
function renderDone() {
  const total = plan ? plan.words.length : 0;
  const remain = pool.length;
  $("doneTitle2").textContent = remain ? "今天到这 ☕" : "今日全部拿下 🎉";
  $("doneLine").innerHTML = remain
    ? `已拿下 <b>${total - remain}</b>/${total} · 剩 ${remain} 个明天继续`
    : `${total} 个词全部通过考试`;
  $("moreBtn").textContent = remain ? "再学一会" : "回味一下（继续转卡片）";
  show("vDone");
}

/* ---------------- 事件 ---------------- */
$("goProbeBtn").addEventListener("click", () => location.href = "/calibrate?probe=1");
$("startPlanBtn").addEventListener("click", async () => {
  await POST("/api/plan_start", {});
  await loadPlan();
  enterLearn();
});
$("lPlayBtn").addEventListener("click", (e) => { e.currentTarget.blur(); playWord(curLearn()); });
$("lRevealBtn").addEventListener("click", (e) => { e.currentTarget.blur(); revealLearn(); });
$("lNextBtn").addEventListener("click", (e) => { e.currentTarget.blur(); nextLearn(); });
$("sceneBtn").addEventListener("click", () => requestScene(nextFive()));
$("sceneAgainBtn").addEventListener("click", () => sceneGroup && requestScene(sceneGroup));
$("examBtn").addEventListener("click", enterExam);
$("examQuitBtn").addEventListener("click", enterLearn);
$("backToLearnBtn").addEventListener("click", enterLearn);
const endDay = async () => { await POST("/api/plan_end", {}); renderDone(); };
$("endDayBtn").addEventListener("click", endDay);
$("endDayBtn2").addEventListener("click", endDay);
$("moreBtn").addEventListener("click", () => {
  if (pool.length) { enterLearn(); }
  else { pool = shuffle(plan.words.slice()); li = 0; enterLearn(); }
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
  toast(r.ok ? `新词配额已改为 ${q}/天` : (r.error || "保存失败"));
});
$("postponeBtn").addEventListener("click", async () => {
  const d = parseInt($("postponeInput").value, 10);
  if (!confirm(`把整个学习计划顺延 ${d} 天？（到期日全部后移，今天的计划作废）`)) return;
  const r = await POST("/api/postpone", { days: d });
  if (r.ok) { toast(`已放假 ${d} 天，好好休息 ☕`); $("cfgModal").classList.add("hidden"); boot(); }
});

boot();
