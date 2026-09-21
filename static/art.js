/* maidcafe art loader — 画稿按固定路径挂载。
 * 换图 = 同名覆盖 static/art/ 下的文件，代码零改动；
 * 文件不存在时 <img onerror> 自删，图位无痕消失（画稿可以来一张亮一张）。 */

const ART = {
  logo:      "/static/art/A1_logo.png",
  welcome:   "/static/art/C1_welcome.png",
  empty:     "/static/art/C2_empty.png",
  cooking:   "/static/art/C3_cooking.png",
  celebrate: "/static/art/C4_celebrate.png",
  error:     "/static/art/C5_error.png",
  avatars: {
    haruka:  "/static/art/V1_haruka.png",
    momo:    "/static/art/V2_momo.png",
    shizuku: "/static/art/V3_shizuku.png",
    suzu:    "/static/art/V4_suzu.png",
    aoi:     "/static/art/V5_aoi.png",
  },
};

/* 横幅图位 HTML（插进 innerHTML 用） */
function artBanner(key, cls) {
  const src = ART[key];
  return src
    ? `<img class="art-banner${cls ? " " + cls : ""}" src="${src}" alt="" onerror="this.remove()">`
    : "";
}

/* 说话人头像（女仆有，客人返回空串不占位） */
function artAvatar(speaker) {
  const src = ART.avatars[(speaker || "").toLowerCase()];
  return src ? `<img class="spk-avatar" src="${src}" alt="" onerror="this.remove()">` : "";
}

/* 品牌位：A1 logo 就位后替换 ☕，并顺带升级 favicon */
(function mountBrandLogo() {
  const cup = document.querySelector(".brand .cup");
  if (!cup) return;
  const img = new Image();
  img.onload = () => {
    img.className = "brand-logo";
    cup.textContent = "";
    cup.appendChild(img);
    const link = document.querySelector('link[rel="icon"]');
    if (link) link.href = ART.logo;
  };
  img.src = ART.logo;
})();
