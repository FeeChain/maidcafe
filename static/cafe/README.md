# 窗边美术与音频

本轮插画通过内置 image generation 工具生成，并已复制到项目内。保留原有 Momo 头像与旧插画，新图作为迎宾、等候及收尾场景使用。

- `window-seat.jpg`，新增窗边迎宾场景。
- `../art/V1_haruka.png`，Haruka 头像。
- `../art/V3_shizuku.png`，Shizuku 头像。
- `../art/V4_suzu.png`，Suzu 头像。
- `../art/V5_aoi.png`，Aoi 头像。

四名新店员为第一版头像设计，尚无完整三视图、全身立绘及表情差分。角色性格与配音映射以 `roster.json` 为准。

## 复用提示词规格

### 窗边场景

Use case: illustration-story. A first-person guest view from a window seat inside a cozy Japanese manga-style maid cafe. Adult Momo, pink hair, black-and-white maid uniform, gently places a cup of tea in front of the viewer. Adult Shizuku prepares coffee behind the wooden counter. Warm amber light, rainy window, detailed wood and porcelain, quiet inviting atmosphere, expressive anime illustration. No logos, captions, UI, or watermark. Designed as an immersive wide welcome illustration with a clear foreground table.

### 店员头像

Use case: stylized-concept. A coordinated 2-by-2 atlas of four adult maid cafe character bust portraits, consistent anime illustration, warm cream background, clear separation between quadrants, no text or watermark. Top-left Haruka, calm responsible manager. Top-right Shizuku, cool deadpan kitchen lead. Bottom-left Suzu, cheerful accident-prone floor waitress. Bottom-right Aoi, earnest trainee. Distinct hairstyles and expressions, modest black-and-white maid uniforms, readable at small avatar size. Match the cafe's warm manga atmosphere.

以上是已选素材的维护与重绘规格，不保证后续生成与本版像素一致。

## 离线招待

`window-seat.mp3` 为原创四句招待对话的本地 Kokoro 配音，英文全文在 `static/home.html` 中。浏览器原生音频控件支持暂停、拖动与键盘操作。切换到词卡或离开菜单时自动暂停。
