/* Cafe art changes at a stage boundary, never on a timer or a word turn. */
const ART_MISSING = new Set();
function artGone(img) {
  ART_MISSING.add(img.getAttribute("src"));
  img.hidden = true;
}
const ART = {
  logo: "/static/art/A1_logo.png",
  empty: "/static/cafe/scenes/rainy-table.webp",
  avatars: {
    haruka: "/static/cafe/avatars/haruka-avatar-v3.webp", momo: "/static/cafe/avatars/momo-avatar-v3.webp",
    shizuku: "/static/cafe/avatars/shizuku-avatar-v3.webp", suzu: "/static/cafe/avatars/suzu-avatar-v3.webp",
    aoi: "/static/cafe/avatars/aoi-avatar-v3.webp",
  },
};
const CAFE_CAST = {
  haruka: {name: "Haruka", role: "店长", line: "慢慢来，茶还热着。"},
  momo: {name: "Momo", role: "看板娘", line: "今天也给你留了窗边的位置。"},
  shizuku: {name: "Shizuku", role: "后厨", line: "先歇一会儿，我来准备。"},
  suzu: {name: "Suzu", role: "大厅接待", line: "坐舒服一点，再听一个词吧。"},
  aoi: {name: "Aoi", role: "实习店员", line: "我陪你一起，翻过这一页。"},
};
const CAFE_SCENES = {
  morning: {file: "scenes/arrival-morning-v3.webp", cast: "haruka", caption: "晨光 · 推门入座", alt: "晨光里，Haruka 邀你到窗边坐下。", focus: "31% 40%"},
  window: {file: "scenes/window-seat-v3.webp", cast: "momo", caption: "窗边 · 第一杯茶", alt: "Momo 递来茶杯，Shizuku 在吧台准备咖啡。", focus: "62% 44%"},
  welcome: {file: "scenes/welcome-suzu-v3.webp", cast: "suzu", caption: "雨夜 · 有位等你", alt: "Suzu 端着热茶，在暖灯下迎接你。", focus: "49% 40%"},
  study: {file: "scenes/study-aoi-v3.webp", cast: "aoi", caption: "午后 · 单词手帖", alt: "Aoi 坐在桌对面，陪你翻开手帖。", focus: "60% 38%"},
  reading: {file: "scenes/reading-haruka-v3.webp", cast: "haruka", caption: "书页间 · 一个小故事", alt: "Haruka 在窗边翻开书，准备分享一个故事。", focus: "40% 38%"},
  tea: {file: "scenes/tea-shizuku-v3.webp", cast: "shizuku", caption: "吧台 · 正在温茶", alt: "Shizuku 在木吧台后，安静地往花纹瓷杯里倒茶。", focus: "42% 40%"},
  rest: {file: "scenes/rest-momo-v3.webp", cast: "momo", caption: "晚霞 · 歇一小会儿", alt: "Momo 捧着茶杯，陪你在晚霞里休息。", focus: "40% 42%"},
  rain: {file: "scenes/rainy-table.webp", cast: "shizuku", caption: "听雨 · 留一点空白", alt: "雨落在窗外，桌上放着热茶、书和白色小花。", focus: "60% 55%"},
};
// Each stage has at least three appropriate scenes. Cast also follows the scene.
const CAFE_POOLS = {
  welcome: ["morning", "window", "welcome"], menu: ["window", "rest", "morning"],
  study: ["study", "reading", "rain"], recall: ["reading", "study", "rain"],
  prepare: ["tea", "window", "rain"], story: ["reading", "rest", "study"],
  rest: ["rest", "rain", "tea"], empty: ["rain", "welcome", "rest"],
  history: ["reading", "rest", "rain"], wordbook: ["study", "reading", "rain"],
  calibrate: ["study", "reading", "rain"], settings: ["tea", "rain", "morning"],
  setup: ["tea", "window", "welcome"], word: ["study", "reading", "rest"],
  error: ["rain", "tea", "rest"],
};
function artBanner(key, cls) {
  const src = ART[key];
  return src && !ART_MISSING.has(src)
    ? `<img class="art-banner${cls ? " " + cls : ""}" src="${src}" alt="" onerror="artGone(this)">` : "";
}
function artAvatar(speaker) {
  const src = ART.avatars[(speaker || "").toLowerCase()];
  return src && !ART_MISSING.has(src)
    ? `<img class="spk-avatar" src="${src}" alt="" onerror="artGone(this)">` : "";
}

const CafeArt = (() => {
  let mode = "rotate";
  const states = new Map(), bags = new Map(), last = new Map();
  // The desktop uses a private loopback origin. Keep the bag across page links
  // and reloads for this visit; preferences themselves live in the local DB.
  try {
    const saved = JSON.parse(sessionStorage.getItem("mc_cafe_art_rotation") || "{}");
    Object.entries(CAFE_POOLS).forEach(([stage, pool]) => {
      const item = saved[stage];
      if (item && Array.isArray(item.bag) && new Set(item.bag).size === item.bag.length &&
          item.bag.every(id => pool.includes(id)) && pool.includes(item.last)) {
        bags.set(stage, item.bag); last.set(stage, item.last);
      }
    });
  } catch (_) { /* Restricted storage must not prevent learning. */ }
  function pick(stage) {
    const pool = CAFE_POOLS[stage] || CAFE_POOLS.rest;
    if (mode === "fixed") return pool[0];
    let bag = bags.get(stage) || [];
    if (!bag.length) {
      bag = pool.slice();
      for (let i = bag.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [bag[i], bag[j]] = [bag[j], bag[i]];
      }
      if (bag.length > 1 && bag[0] === last.get(stage)) [bag[0], bag[1]] = [bag[1], bag[0]];
    }
    const id = bag.shift(); bags.set(stage, bag); last.set(stage, id);
    try {
      const saved = {};
      bags.forEach((remaining, key) => saved[key] = {bag: remaining, last: last.get(key)});
      sessionStorage.setItem("mc_cafe_art_rotation", JSON.stringify(saved));
    } catch (_) {}
    return id;
  }
  function putImage(img, src, alt) {
    if (img.getAttribute("src") !== src) img.src = src;
    img.alt = alt;
    img.hidden = ART_MISSING.has(src);
    img.decoding = "async";
    img.onerror = () => artGone(img);
  }
  function render(root, id) {
    const scene = CAFE_SCENES[id], cast = CAFE_CAST[scene.cast];
    root.dataset.cafeSceneId = id;
    root.querySelectorAll("[data-cafe-scene]").forEach(img => {
      putImage(img, "/static/cafe/" + scene.file, scene.alt);
      img.style.objectPosition = scene.focus;
    });
    root.querySelectorAll("[data-cafe-cast]").forEach(img =>
      putImage(img, `/static/cafe/cast/${scene.cast}-full-v3.webp`, `${cast.name}，${cast.role}`));
    root.querySelectorAll("[data-cafe-caption]").forEach(el => el.textContent = scene.caption);
    root.querySelectorAll("[data-cafe-name]").forEach(el => el.textContent = cast.name);
    root.querySelectorAll("[data-cafe-line]").forEach(el => el.textContent = cast.line);
    root.querySelectorAll("[data-cafe-avatar]").forEach(img => putImage(img, ART.avatars[scene.cast], ""));
  }
  function refresh(force = false) {
    states.forEach((state, root) => {
      const visible = !root.closest(".hidden, [hidden]");
      const stage = root.dataset.cafeStage;
      const entered = visible && (!state.visible || state.stage !== stage);
      if (visible && mode !== "quiet" && (force || entered || !state.id)) {
        if (mode === "fixed" || !state.id || state.choiceStage !== stage || (entered && !root.hasAttribute("data-cafe-still"))) {
          state.id = pick(stage);
          state.choiceStage = stage;
        }
        render(root, state.id);
      }
      state.visible = visible; state.stage = stage;
    });
  }
  function setMode(value) {
    mode = ["rotate", "fixed", "quiet"].includes(value) ? value : "rotate";
    document.body.dataset.cafeArt = mode;
    document.querySelectorAll("[data-cafe-mode]").forEach(el => el.value = mode);
    refresh(true);
  }
  const ready = fetch("/api/config").then(r => { if (!r.ok) throw new Error(); return r.json(); })
    .catch(() => ({})).then(config => {
      const observer = new MutationObserver(() => refresh());
      document.querySelectorAll("[data-cafe-stage]").forEach(root => {
        states.set(root, {visible: false});
        observer.observe(root, {attributes: true, attributeFilter: ["class", "hidden", "data-cafe-stage"]});
      });
      setMode(config.art_mode);
      document.body.classList.add("cafe-art-ready");
    });
  document.querySelectorAll("[data-cafe-mode]").forEach(select => {
    select.addEventListener("change", async () => {
      const value = select.value, status = document.getElementById("appearanceStatus");
      select.disabled = true;
      if (status) status.textContent = "正在保存…";
      try {
        const r = await fetch("/api/config", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({art_mode: value})});
        if (!r.ok) throw new Error();
        setMode(value);
        if (status) status.textContent = "已保存，下次打开也会记得。";
      } catch (_) {
        select.value = mode;
        if (status) status.textContent = "暂时没保存成功，请再试一次。";
      } finally { select.disabled = false; }
    });
  });
  return {ready};
})();

(function mountBrandLogo() {
  const cup = document.querySelector(".brand .cup");
  if (!cup) return;
  const img = new Image();
  img.onload = () => {
    img.className = "brand-logo"; cup.textContent = ""; cup.appendChild(img);
    const link = document.querySelector('link[rel="icon"]');
    if (link) link.href = ART.logo;
  };
  img.src = ART.logo;
})();
