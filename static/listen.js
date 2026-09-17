/* maidcafe 听力室 — dialogue player. */

const $ = (id) => document.getElementById(id);
const fetchJSON = async (url, opts) => (await fetch(url, opts)).json();

const SPEAKER_COLORS = ["#a4632e", "#b0518a", "#4a7fa5", "#5f8f57", "#8a6bb8",
                        "#c08a2d", "#c0574f"];

let dialogues = [];
let current = null;      // full dialogue object
let turnIdx = -1;
let playing = false;
let loop = false;
let audioEl = null;
let played = new Set();  // revealed turns (progressive mode)
let speakerColor = {};
let genPolling = null;

let listenedReported = false;

/* ---------------- list view ---------------- */
let dailyEmpty = false;

async function loadDailyStatus() {
  const s = await fetchJSON("/api/daily_status");
  dailyEmpty = s.due === 0 && s.backlog === 0;
  if (dailyEmpty) {
    // A1: 空池引导态——主按钮变成去校准
    $("dailyBtn").textContent = "去校准 →";
    $("dailyLine").innerHTML =
      "<b>先认识你，再给你听。</b>随便过 1 组词（约 3 分钟），女仆们就知道该用什么词跟客人说话了。";
  } else if (!localStorage.getItem("mc_gen_pending")) {
    $("dailyBtn").textContent = "☕ 今日任务";
    $("dailyBtn").disabled = false;
    $("dailyLine").textContent =
      `到期复习 ${s.due} · 排队中 ${s.backlog} · 学习中 ${s.learning} · 已毕业 ${s.graduated}`;
  }
}

async function loadList() {
  loadDailyStatus();
  dialogues = await fetchJSON("/api/dialogues");
  const box = $("dialogueList");
  box.innerHTML = "";
  if (!dialogues.length) {
    box.innerHTML = '<p class="empty">还没有对话——先在校准页积累生词，然后点上面的按钮生成。</p>';
    return;
  }
  let listenedRec = {};
  try { listenedRec = JSON.parse(localStorage.getItem("mc_listened") || "{}"); } catch (_) {}
  dialogues.forEach((d) => {
    const el = document.createElement("div");
    el.className = "ditem";
    const date = new Date(d.ts * 1000).toLocaleDateString("zh-CN",
      { month: "numeric", day: "numeric" });
    const heard = listenedRec[d.id] ? ` · <span class="s3">已听完 ${listenedRec[d.id]}</span>` : "";
    el.innerHTML =
      `<div class="d-top"><b>#${d.id}</b> · ${date} · ${d.n_turns} 轮 · ` +
      `${d.characters.join("、")}${heard}</div>` +
      `<div class="d-scene">${d.scene}</div>` +
      `<div class="d-targets">${d.targets.map(t =>
        `<span class="chip">${t}</span>`).join("")}</div>`;
    el.addEventListener("click", () => openDialogue(d.id));
    box.appendChild(el);
  });
}

/* ---------------- player ---------------- */
async function openDialogue(id) {
  current = await fetchJSON("/api/dialogue/" + id);
  turnIdx = -1;
  playing = false;
  listenedReported = false;
  played = new Set();
  revealedOnce = new Set();
  speakerColor = {};
  let ci = 0;
  current.turns.forEach((t) => {
    if (!(t.speaker in speakerColor)) {
      speakerColor[t.speaker] = SPEAKER_COLORS[ci++ % SPEAKER_COLORS.length];
    }
  });
  $("listView").classList.add("hidden");
  $("wordbookView").classList.add("hidden");
  $("playerView").classList.remove("hidden");
  $("sceneLine").textContent = `#${current.id} · ${current.scene}`;
  $("targetChips").innerHTML = current.targets.map((t) =>
    `<span class="chip target-chip" data-word="${t.word}">${t.word}` +
    `<small> ${t.definition.split("\n")[0].slice(0, 24)}</small></span>`).join("");
  document.querySelectorAll(".target-chip").forEach((el) =>
    el.addEventListener("click", () => showWordCard(el.dataset.word)));
  const ratio = current.report.known_ratio;
  $("ratioBadge").textContent = ratio != null
    ? `周边词汇 ${(ratio * 100).toFixed(0)}% 在你的已知范围内` : "";
  renderTurns();
  updatePlayBtn();
}

function matchTarget(token) {
  const lw = token.toLowerCase();
  const t = current.targets.find((x) => {
    const w = x.word.toLowerCase();
    return lw === w || (lw.startsWith(w) && lw.length - w.length <= 3) ||
           (w.startsWith(lw) && w.length - lw.length <= 1);
  });
  return t ? t.word : null;
}

/* every word is clickable (lookup / add-to-wordbook); targets are red */
function highlightTargets(text) {
  return text.replace(/[A-Za-z][A-Za-z']*/g, (m) => {
    if (m.length <= 2) return m;
    const target = matchTarget(m);
    const cls = target ? "wclick tword" : "wclick";
    const word = target || m.toLowerCase();
    return `<span class="${cls}" data-word="${word}">${m}</span>`;
  });
}

let revealedOnce = new Set();  // C4: 纯听模式下被单独揭示的轮

function renderTurns() {
  const mode = $("subMode").value;
  const box = $("turnList");
  box.innerHTML = "";
  // D3: 进度 + 机制说明
  $("turnProgress").textContent =
    `${played.size} / ${current.turns.length} 轮 · 听完全部轮次算一次复习`;
  current.turns.forEach((t, i) => {
    const el = document.createElement("div");
    el.className = "turn" + (i === turnIdx ? " current" : "");
    const show = mode === "full" ||
      (mode === "progressive" && played.has(i)) ||
      (mode === "pure" && revealedOnce.has(i));
    const color = speakerColor[t.speaker] || "#999";
    let inner =
      `<span class="spk" style="color:${color}">${t.speaker}</span>` +
      (show ? `<span class="txt">${highlightTargets(t.text)}</span>`
            : `<span class="txt veiled">●●●</span>`);
    // C4: 纯听模式当前轮给一个"只揭示这一句"的出口
    if (mode === "pure" && !show && i === turnIdx) {
      inner += `<button class="mk small reveal-one" title="只揭示这一句，不切换模式">揭示这一句</button>`;
    }
    el.innerHTML = inner;
    el.addEventListener("click", () => playTurn(i));
    const rv = el.querySelector(".reveal-one");
    if (rv) rv.addEventListener("click", (e) => {
      e.stopPropagation();
      revealedOnce.add(i);
      renderTurns();
    });
    box.appendChild(el);
  });
  document.querySelectorAll(".wclick").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      showWordCard(el.dataset.word);
    });
  });
  const cur = box.querySelector(".current");
  if (cur) cur.scrollIntoView({ block: "center", behavior: "smooth" });
}

function playTurn(i) {
  if (!current || i < 0 || i >= current.turns.length) return;
  turnIdx = i;
  played.add(i);
  playing = true;
  if (audioEl) audioEl.pause();
  const file = current.files[i];
  if (!file) { onTurnEnd(); return; }
  audioEl = new Audio(`/dialogue_audio/${current.id}/${file}`);
  audioEl.onended = onTurnEnd;
  audioEl.play().catch(() => {});
  renderTurns();
  updatePlayBtn();
}

function reportListened() {
  if (listenedReported || !current) return;
  // 完整听过一遍才算复习(所有轮次都播放过)
  if (played.size < current.turns.length) return;
  listenedReported = true;
  fetchJSON("/api/listened", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id }),
  }).then(() => {
    loadDailyStatus();
    // D3: 本地记听完日期，列表卡显示回执
    try {
      const rec = JSON.parse(localStorage.getItem("mc_listened") || "{}");
      rec[current.id] = new Date().toISOString().slice(5, 10).replace("-", "-");
      localStorage.setItem("mc_listened", JSON.stringify(rec));
    } catch (_) {}
  });
}

function onTurnEnd() {
  if (!playing) return;
  if (turnIdx + 1 < current.turns.length) {
    playTurn(turnIdx + 1);
  } else {
    reportListened();
    if (loop) {
      playTurn(0);
    } else {
      playing = false;
      updatePlayBtn();
    }
  }
}

function togglePlay() {
  if (!current) return;
  if (playing) {
    playing = false;
    if (audioEl) audioEl.pause();
  } else {
    playing = true;
    if (audioEl && audioEl.paused && turnIdx >= 0 && !audioEl.ended) {
      audioEl.play().catch(() => {});
    } else {
      playTurn(turnIdx < 0 ? 0 : turnIdx);
    }
  }
  updatePlayBtn();
}

function updatePlayBtn() {
  $("playBtn2").textContent = playing ? "⏸ 暂停" : "▶ 播放";
}

/* ---------------- word card ---------------- */
let pausedByCard = false;

async function showWordCard(word, opts) {
  opts = opts || {};
  const t = current
    ? current.targets.find((x) => x.word.toLowerCase() === word.toLowerCase())
    : null;
  let info = t;
  let showAdd = false;
  let graduated = !!opts.graduated;
  if (!t) {
    info = await fetchJSON("/api/lookup?word=" + encodeURIComponent(word));
    showAdd = !info.in_wordbook && !info.known && !info.error;
    if (info.known) graduated = true;
  }
  // C2: 点词自动暂停，且暂停可见
  pausedByCard = false;
  if (playing) {
    playing = false;
    if (audioEl) audioEl.pause();
    updatePlayBtn();
    pausedByCard = true;
  }
  $("wcPauseNote").textContent = pausedByCard ? "已为你暂停 · 关闭后从本轮继续" : "";
  $("wcWord").textContent = word;
  $("wcPhon").textContent = (info && info.phonetic) || "";
  $("wcDef").textContent = (info && info.definition) || "（词典里没查到）";
  const addBtn = $("wcAdd");
  addBtn.classList.toggle("hidden", !showAdd && !graduated);
  addBtn.textContent = graduated ? "↺ 再学一遍" : "＋ 加入生词本";
  addBtn.onclick = async () => {
    if (graduated) {
      await wordAction("/api/word/readd", word);
      addBtn.textContent = "✓ 已回到生词池";
    } else {
      await fetchJSON("/api/wordbook_add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ word }),
      });
      addBtn.textContent = "✓ 已加入 · 下次会出现在新的对话里";
      loadDailyStatus();
    }
    setTimeout(() => { addBtn.classList.add("hidden"); }, 2500);
  };
  $("wcPlay").onclick = () => new Audio("/audio/" + encodeURIComponent(word))
    .play().catch(() => {});
  $("wordCard").classList.remove("hidden");
}

$("wcClose").addEventListener("click", () => {
  $("wordCard").classList.add("hidden");
  if (pausedByCard && current) {
    pausedByCard = false;
    playing = true;
    playTurn(Math.max(0, turnIdx));  // 从被打断的这一轮重来
  }
});

/* ---------------- wordbook ---------------- */
async function wordAction(url, word) {
  await fetchJSON(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ word }),
  });
  loadWordbook();
  loadDailyStatus();
}

/* B1: 动作后 6 秒撤销回执条 */
let toastTimer = null;
function showToast(msg, undoUrl, word) {
  $("toastMsg").textContent = msg;
  $("toastUndo").classList.toggle("hidden", !undoUrl);
  $("toastUndo").onclick = undoUrl
    ? () => { wordAction(undoUrl, word); hideToast(); }
    : null;
  $("toast").classList.remove("hidden");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 6000);
}
function hideToast() { $("toast").classList.add("hidden"); }

async function learnedWithUndo(word) {
  await wordAction("/api/word/learned", word);
  showToast(`${word} 已毕业`, "/api/word/readd", word);
}
async function unfamiliarGuarded(w) {
  // 高梯级的词打回会清进度，问一次
  if (w.srs && w.srs.level >= 2 &&
      !confirm(`「${w.word}」已爬到第 ${w.srs.level} 级，打回将从第 1 级重来，确定？`)) return;
  await wordAction("/api/word/unfamiliar", w.word);
  showToast(`${w.word} 已打回 · 明天会再听到`, null, null);
}

function srsBadge(w) {
  if (!w.srs) return '<span class="wb-srs pool">生词池</span>';
  if (w.srs.due) return '<span class="wb-srs due">今日到期</span>';
  return `<span class="wb-srs">第${w.srs.level}级 · ${w.srs.due_in_days}天后</span>`;
}

async function loadWordbook() {
  const data = await fetchJSON("/api/wordbook");
  const box = $("wordbookList");
  const words = data.learning || [];
  box.innerHTML = words.length ? "" : '<p class="empty">生词本还是空的。</p>';
  words.forEach((w) => {
    const el = document.createElement("div");
    el.className = "wb-item";
    const dl = w.dialogues.map((d) => `#${d.id}`).join(" ");
    el.innerHTML =
      `<div class="wb-head"><b>${w.word}</b> <span class="wb-phon">${w.phonetic}</span>` +
      (w.has_audio ? ' <button class="wb-play">🔊</button>' : "") +
      srsBadge(w) +
      `<span class="wb-dl">${dl ? "出现于 " + dl : "尚未生成对话"}</span>` +
      `<button class="mk small wb-learned" title="跳过剩下的复习，直接毕业">我学会了</button>` +
      `<button class="mk small wb-unfam" title="回到第 1 级，明天再听一次">打回重听</button></div>` +
      `<div class="wb-def">${(w.definition || "").split("\n")[0]}</div>`;
    const btn = el.querySelector(".wb-play");
    if (btn) btn.addEventListener("click", () =>
      new Audio("/audio/" + encodeURIComponent(w.word)).play().catch(() => {}));
    el.querySelector(".wb-learned").addEventListener("click", () =>
      learnedWithUndo(w.word));
    el.querySelector(".wb-unfam").addEventListener("click", () =>
      unfamiliarGuarded(w));
    box.appendChild(el);
  });

  /* B3: 毕业区折叠 + 搜索 + 点词开释义卡（卡内再学一遍） */
  const gbox = $("gradList");
  const grads = data.graduated || [];
  $("gradCount").textContent = grads.length ? `${grads.length} 词` : "";
  const renderGrads = (filter) => {
    const list = filter
      ? grads.filter((w) => w.word.includes(filter.toLowerCase()))
      : grads;
    gbox.innerHTML = list.length ? "" : '<p class="empty">没有匹配的毕业词。</p>';
    list.forEach((w) => {
      const el = document.createElement("div");
      el.className = "wb-item";
      el.style.cursor = "pointer";
      el.innerHTML =
        `<div class="wb-head"><b>${w.word}</b> <span class="wb-phon">${w.phonetic}</span>` +
        `<span class="wb-dl">点击查看 / 再学一遍</span></div>`;
      el.addEventListener("click", () => showWordCard(w.word, { graduated: true }));
      gbox.appendChild(el);
    });
  };
  renderGrads("");
  $("gradSearch").oninput = (e) => renderGrads(e.target.value.trim());
}

/* ---------------- generation ---------------- */
async function generate(words) {
  await fetchJSON("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(words ? { words } : { auto: 6 }),
  });
  const before = dialogues.length;
  $("genStatus").textContent = "生成中…（约 1-3 分钟，含配音）";
  if (genPolling) clearInterval(genPolling);
  genPolling = setInterval(async () => {
    const list = await fetchJSON("/api/dialogues");
    const done = list.filter((d) => d.status === "done");
    if (done.length > dialogues.filter((d) => d.status === "done").length ||
        list.length > before && list[0].status === "done") {
      clearInterval(genPolling);
      genPolling = null;
      $("genStatus").textContent = "";
      loadList();
    }
  }, 5000);
}

/* ---------------- wiring ---------------- */
/* A2: 生成中状态可见 + localStorage 记 pending，离开再回来能续上 */
function startGenWatch(expect, label) {
  localStorage.setItem("mc_gen_pending", JSON.stringify({ expect, label }));
  $("dailyBtn").disabled = true;
  $("dailyBtn").textContent = "正在备料…";
  $("genStatus").textContent =
    label + "（约 1-2 分钟一段，可以先去校准，好了会出现在列表顶部）";
  $("genStatus").classList.add("working");
  if (genPolling) clearInterval(genPolling);
  genPolling = setInterval(async () => {
    const list = await fetchJSON("/api/dialogues");
    const done = list.filter((d) => d.status === "done").length;
    if (done > dialogues.filter((d) => d.status === "done").length) loadList();
    if (done >= expect) {
      clearInterval(genPolling);
      genPolling = null;
      localStorage.removeItem("mc_gen_pending");
      $("dailyBtn").disabled = false;
      $("genStatus").textContent = "对话全部就绪，请慢用 ☕";
      setTimeout(() => {
        $("genStatus").textContent = "";
        $("genStatus").classList.remove("working");
      }, 5000);
      loadDailyStatus();
    }
  }, 5000);
}

$("dailyBtn").addEventListener("click", async () => {
  if (dailyEmpty) { location.href = "/"; return; }
  if ($("dailyBtn").disabled) return;
  const r = await fetchJSON("/api/daily_task", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_quota: 5 }),
  });
  if (!r.chunks || !r.chunks.length) {
    $("genStatus").textContent = r.message || "今天没有到期词";
    setTimeout(() => { $("genStatus").textContent = ""; }, 4000);
    return;
  }
  const n = r.chunks.flat().length;
  const doneBefore = dialogues.filter((d) => d.status === "done").length;
  startGenWatch(doneBefore + r.chunks.length,
    `今天先取 ${n} 个词 · ${r.chunks.length} 段对话正在备料`);
});

/* 页面加载时恢复未完成的生成状态 */
(function resumeGenWatch() {
  try {
    const p = JSON.parse(localStorage.getItem("mc_gen_pending") || "null");
    if (p && p.expect) {
      fetchJSON("/api/dialogues").then((list) => {
        dialogues = list;
        const done = list.filter((d) => d.status === "done").length;
        if (done >= p.expect) {
          localStorage.removeItem("mc_gen_pending");
        } else {
          startGenWatch(p.expect, p.label || "对话正在备料");
        }
      });
    }
  } catch (_) {}
})();
/* B4: 加词四态——先查再判断 */
async function tryAddWord() {
  const w = $("addWordInput").value.trim().toLowerCase();
  if (!w) return;
  const info = await fetchJSON("/api/lookup?word=" + encodeURIComponent(w));
  const msg = $("addWordMsg");
  if (!info.definition) {
    msg.innerHTML = `<span class="s1">词典里没有「${w}」</span>`;
  } else if (info.in_wordbook) {
    msg.textContent = `「${w}」已在生词池里了`;
  } else if (info.known) {
    msg.innerHTML = `「${w}」已经毕业了 —— `;
    const b = document.createElement("button");
    b.className = "mk small";
    b.textContent = "再学一遍";
    b.onclick = async () => {
      await wordAction("/api/word/readd", w);
      msg.textContent = `✓ 「${w}」已回到生词池`;
      $("addWordInput").value = "";
    };
    msg.appendChild(b);
    return;  // 不自动清除，等用户决定
  } else {
    await fetchJSON("/api/wordbook_add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: w }),
    });
    msg.textContent = `✓ 「${w}」已加入 · 下次会出现在新的对话里`;
    $("addWordInput").value = "";
    loadWordbook();
    loadDailyStatus();
  }
  setTimeout(() => { msg.textContent = ""; }, 4000);
}
$("addWordBtn").addEventListener("click", tryAddWord);
$("addWordInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") tryAddWord();
});
$("genBtn").addEventListener("click", () => generate(null));
$("genCustomBtn").addEventListener("click", () => {
  const raw = $("customWords").value.trim();
  if (raw) generate(raw.split(/[,，\s]+/).filter(Boolean));
});
$("backBtn").addEventListener("click", () => {
  playing = false;
  if (audioEl) audioEl.pause();
  $("playerView").classList.add("hidden");
  $("listView").classList.remove("hidden");
  loadList();
});
$("playBtn2").addEventListener("click", togglePlay);
$("prevBtn").addEventListener("click", () => playTurn(Math.max(0, turnIdx - 1)));
$("nextBtn").addEventListener("click", () =>
  playTurn(Math.min(current.turns.length - 1, turnIdx + 1)));
$("loopBtn").addEventListener("click", () => {
  loop = !loop;
  $("loopBtn").textContent = "循环: " + (loop ? "开" : "关");
});
$("subMode").addEventListener("change", renderTurns);
$("delBtn").addEventListener("click", async () => {
  if (!current) return;
  if (!confirm(`删除对话 #${current.id}？`)) return;
  await fetchJSON("/api/dialogue_delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: current.id }),
  });
  $("backBtn").click();
});
$("tabList").addEventListener("click", () => {
  $("tabList").classList.add("active");
  $("tabWordbook").classList.remove("active");
  $("wordbookView").classList.add("hidden");
  $("playerView").classList.add("hidden");
  $("listView").classList.remove("hidden");
  loadList();
});
$("tabWordbook").addEventListener("click", () => {
  $("tabWordbook").classList.add("active");
  $("tabList").classList.remove("active");
  $("listView").classList.add("hidden");
  $("playerView").classList.add("hidden");
  $("wordbookView").classList.remove("hidden");
  loadWordbook();
});

document.addEventListener("keydown", (e) => {
  if (e.key === " " && !$("playerView").classList.contains("hidden") &&
      e.target.tagName !== "INPUT") {
    e.preventDefault();
    togglePlay();
  }
});

loadList();
