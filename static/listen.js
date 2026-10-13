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
async function loadList() {
  dialogues = await fetchJSON("/api/dialogues");
  const box = $("dialogueList");
  box.innerHTML = "";
  if (!dialogues.length) {
    // 对话只从主页学习里的篮子煮（今日任务入口 10-13 已删）
    box.insertAdjacentHTML("beforeend", artBanner("empty") +
      '<p class="empty">还没有对话——在<a href="/">主页</a>翻卡攒词，点「☕ 给这几个词来一场对话」，煮好的都会出现在这里。</p>');
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
    let state = "";
    if (d.status === "writing") {
      state = ` · <span class="s2">☕ 写稿中${d.progress && d.progress.startsWith("attempt")
        ? "（第" + d.progress.slice(8) + "稿）" : ""}</span>`;
    } else if (d.status === "tts") {
      state = ` · <span class="s2">🔊 配音中</span>`;
    } else if (d.status === "error") {
      state = ` · <span class="s1">✗ 翻车了：${d.error || ""}（点击删除）</span>`;
    }
    el.innerHTML =
      `<div class="d-top"><b>#${d.id}</b> · ${date} · ${d.n_turns} 轮 · ` +
      `${d.characters.join("、")}${heard}${state}</div>` +
      `<div class="d-scene">${d.scene}</div>`;   // 不挂目标词：盲听不剧透（FLOW 全局）
    if (d.status === "error") {
      el.addEventListener("click", async () => {
        if (!confirm(`删除翻车的对话 #${d.id}？`)) return;
        await fetchJSON("/api/dialogue_delete", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: d.id }),
        });
        loadList();
      });
    } else if (d.status === "writing" || d.status === "tts") {
      el.style.cursor = "default";
    } else {
      el.addEventListener("click", () => openDialogue(d.id));
    }
    box.appendChild(el);
  });
}

/* ---------------- player ---------------- */
async function openDialogue(id) {
  window.__mcview = "player#" + id;
  if (window.mclog) mclog("view", "player#" + id);
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
    `${played.size} / ${current.turns.length} 轮`;
  current.turns.forEach((t, i) => {
    const el = document.createElement("div");
    el.className = "turn" + (i === turnIdx ? " current" : "");
    const show = mode === "full" ||
      (mode === "progressive" && played.has(i)) ||
      (mode === "pure" && revealedOnce.has(i));
    const color = speakerColor[t.speaker] || "#999";
    let inner =
      `<span class="spk" style="color:${color}">${artAvatar(t.speaker)}${t.speaker}</span>` +
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
  // 无论是否 target 命中，都查一次在池/毕业标志——
  // 否则毕业的目标词会丢「↺ 再学一遍」按钮（TESTPLAN D03 抓到的 bug）
  let flags = {};
  try {
    flags = await fetchJSON("/api/lookup?word=" + encodeURIComponent(word));
  } catch (_) {}
  const info = t || flags;
  const showAdd = !!flags.definition && !flags.in_wordbook &&
                  !flags.known && !flags.error;
  let graduated = !!opts.graduated || !!flags.known;
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
  $("wcMorph").innerHTML = morphHTML(flags.morph);
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
  // 「还是不熟」= 按考挂处理：记忆减半，太低就回生词池（FLOW §4）
  await wordAction("/api/word/unfamiliar", w.word);
  showToast(`${w.word} 已调低记忆程度`, null, null);
}

/* 只给记忆程度，不给"到期/几天后"——不预告（FLOW §4） */
function srsBadge(w) {
  if (!w.srs) return '<span class="wb-srs pool">生词池</span>';
  return `<span class="wb-srs" title="记忆程度 0-100，随时间下降，考过回满">记忆 ${w.srs.weight}</span>`;
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
      (w.srs ? `<button class="mk small wb-unfam" title="按考挂处理：记忆减半">打回重听</button>` : "") +
      `</div>` +
      `<div class="wb-def">${(w.definition || "").split("\n")[0]}</div>`;
    const btn = el.querySelector(".wb-play");
    if (btn) btn.addEventListener("click", () =>
      new Audio("/audio/" + encodeURIComponent(w.word)).play().catch(() => {}));
    el.querySelector(".wb-learned").addEventListener("click", () =>
      learnedWithUndo(w.word));
    const unfam = el.querySelector(".wb-unfam");
    if (unfam) unfam.addEventListener("click", () => unfamiliarGuarded(w));
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
/* 词表导入（FLOW 工具页）：只进生词池；推定已认识的默认不加，给「这些也加上」 */
$("importFile").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (f) $("importText").value = await f.text();
});
async function importWordlist(includeKnown) {
  const text = $("importText").value;
  const msg = $("importMsg");
  if (!text.trim()) return;
  const r = await fetchJSON("/api/wordbook_import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, include_known: includeKnown }),
  });
  if (r.error) { msg.textContent = r.error; return; }
  msg.innerHTML =
    `加入 <b>${r.added_count}</b> 个 · 已在生词本 ${r.already_count} · 已学会 ${r.learned_count}` +
    (r.presumed_count ? ` · 按测定的边界你应该已经认识 ${r.presumed_count} 个（没加）` : "") +
    (r.missing_count ? ` · 查不到 ${r.missing_count} 个：${r.missing.slice(0, 20).join("、")}` : "");
  if (r.presumed_count) {
    const b = document.createElement("button");
    b.id = "importKnownBtn";
    b.className = "mk small";
    b.textContent = "这些也加上";
    b.onclick = () => importWordlist(true);
    msg.appendChild(b);
  }
  loadWordbook();
}
$("importBtn").addEventListener("click", () => importWordlist(false));

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
  $("loopBtn").textContent = "循环：" + (loop ? "开" : "关");
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
  window.__mcview = "list";
  $("tabList").classList.add("active");
  $("tabWordbook").classList.remove("active");
  $("wordbookView").classList.add("hidden");
  $("playerView").classList.add("hidden");
  $("listView").classList.remove("hidden");
  loadList();
});
$("tabWordbook").addEventListener("click", () => {
  window.__mcview = "wordbook";
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

/* 跨页直达：/listen#wordbook 开生词本；/listen#dialogue=N 直接进播放器 */
const dlgHash = location.hash.match(/^#dialogue=(\d+)$/);
if (location.hash === "#wordbook") {
  $("tabWordbook").click();
} else if (dlgHash) {
  loadList();
  openDialogue(parseInt(dlgHash[1], 10));
} else {
  loadList();
}
