# maidcafe ☕ 画稿需求清单（发给画师的完整版）

> 本文件是**美术外包的唯一依据**，比 DESIGN_BRIEF.md §6 更全（含官网与图标衍生需求）。
> 每条 prompt 可直接投喂画师或生图模型。完成一张勾一张。

## 通用风格块（每条 prompt 前置）

```
clean modern Japanese anime style, 2020s TV anime key-visual quality,
soft cel shading, warm cozy cafe lighting, cream and coffee-brown pastel
palette, crisp line art, cheerful slice-of-life mood, no text, no watermark,
high resolution
```

## 交付总则

- 角色类：**PNG 透明底**；插画/背景类：PNG 或高质量 WebP
- 命名按下表 ID（如 `B1_haruka_full.png`），交付后放 `static/art/`
- 色板对齐：奶油底 `#F6F1E7` / 咖啡棕 `#A4632E` / 墨棕 `#3A2F28`（画面主色调靠拢即可，不必精确）
- 全部画面**不带任何文字**

## 总表（按优先级）

| ID | 内容 | 规格 | 用在哪 | 优先 | 状态 |
|---|---|---|---|---|---|
| A1 | Logo / favicon | 1024² 圆徽 | 网站图标、README、桌面图标 | **P0** | ☐ |
| A2 | 官网主视觉（五人合影） | ≥2560×1440 (16:9) | 官网 hero、GitHub 社交卡（裁 1280×640） | **P0** | ☐ |
| C1 | 欢迎页插画（Momo 开门） | ≈1024×640 横幅 | 校准页欢迎卡 | **P0** | ☐ |
| C2 | 空列表插画（窗边空桌） | ≈1024×640 | 听力室空状态 | **P0** | ☐ |
| B1–B5 | 五人全身立绘 | ≥1024×2048 透明底 | 各状态页、官网角色介绍 | P1 | ☐☐☐☐☐ |
| V1–V5 | 五人半身头像 | 512² 透明底 | 字幕说话人头像、生词本 | P1 | ☐☐☐☐☐ |
| C3 | 生成等待（Shizuku 烹制） | ≈1024×640 | 「好一段先听一段」等待条 | P1 | ☐ |
| C4 | 全部完成庆祝（五人欢呼） | ≈1024×640 | 今日任务全部听完 | P1 | ☐ |
| C5 | 错误/404（Suzu 打翻盘子） | ≈1024×640 | 报错页 | P1 | ☐ |
| S1–S4 | 场景背景 ×4 | 16:9 柔焦 | 播放器页头 | P2 | ☐☐☐☐ |
| H1–H5 | 隐藏面彩蛋 ×5 | ≥1024×2048 透明底 | 10% 触发的隐藏面对话专属立绘 | P2 | ☐☐☐☐☐ |
| G1–G3 | 乱入客人头像 ×3 | 512² 透明底 | 30% 乱入客人的字幕头像 | P2 | ☐☐☐ |
| M1 | Momo Q版（chibi） | 512² 透明底 | 每日提醒通知、宣传贴纸 | P2 | ☐ |

---

## A. 品牌

**A1 Logo/favicon**
`circular badge logo, a coffee cup wearing a tiny maid headband ribbon,
coffee-brown on cream, simple enough to read at 32px`
衍生（无需另画，设计裁切即可）：桌面/PWA 图标 1024²（系统自动圆角）、favicon 32²。

**A2 官网主视觉**
`all five maids of a cozy cafe posing together at the counter, welcoming
gesture toward the viewer, warm afternoon light through big windows,
composition leaves clear space on the left third for headline text`
（左三分之一留白给标题文案；GitHub 社交预览 1280×640 从中裁切）

## B. 角色全身立绘（≥1024×2048 透明底）+ V. 半身头像（512²）

每人两件：全身立绘 + 同设定半身头像（头像可从立绘裁绘，表情朝向镜头）。

**B1/V1 Haruka（遥，26，店长）**
`26-year-old cafe manager, long straight dark-navy hair in a low ponytail,
gentle tired amber eyes, elegant burgundy long-skirt maid dress with a white
long apron, small silver pocket-watch chain, holding a clipboard, calm faint
smile with a hint of a sigh, mature graceful posture`

**B2/V2 Momo（莓莓，20，看板娘）**
`20-year-old star waitress, strawberry-pink twin-tails with star hairpins,
big sparkling magenta eyes, bright classic maid outfit with extra frills and
a heart-shaped apron pocket, winking and giving a cheerful welcome pose,
radiating energy`

**B3/V3 Shizuku（雫，22，后厨担当）**
`22-year-old kitchen cook, silver-grey blunt short bob, half-lidded teal
eyes, deadpan minimal expression, dark-green tea apron over a rolled-sleeve
shirt, kitchen headscarf, carrying a tray with perfect effortless posture,
tiny hidden warmth in her look`

**B4/V4 Suzu（铃，19，大厅女仆）**
`19-year-old clumsy floor maid, messy orange side-ponytail, round hazel
eyes, small band-aid on cheek, slightly oversized maid uniform with a
crooked headband, balancing a wobbling stack of teacups, flustered but
cheerful expression`

**B5/V5 Aoi（葵，18，实习生）**
`18-year-old earnest trainee maid, neat black bob with a plain white
headband, sincere violet eyes, trainee ribbon badge, holding a notebook and
pencil, standing perfectly straight with unconscious ballet-like grace,
slightly nervous polite smile`

## C. 状态插画（≈1024×640 横幅，衬奶油底）

| ID | 用途 | prompt（接通用风格块） |
|---|---|---|
| C1 | 欢迎页 | `Momo at the cafe front door holding it open, warm light spilling out, "welcome back" gesture, cozy cafe interior behind` |
| C2 | 空列表 | `an empty cafe table by the window, one steaming coffee cup, soft afternoon light, quiet and inviting` |
| C3 | 生成等待 | `Shizuku in the kitchen calmly cooking, steam rising, ingredients floating like little words around the pot` |
| C4 | 完成庆祝 | `all five maids cheering together in the cafe hall, confetti, warm celebration` |
| C5 | 错误/404 | `Suzu mid-trip with flying teacups frozen in air, comically panicked, other maids reaching to catch the cups` |

## S. 场景背景 ×4（16:9 柔焦，播放器页头）

| ID | prompt |
|---|---|
| S1 | `cafe main hall in warm afternoon light` |
| S2 | `cafe hall on a rainy evening, rain on the window, lamps glowing` |
| S3 | `cafe kitchen before opening, neat and quiet` |
| S4 | `tiny manager's office with schedule board and piled receipts` |

## H. 隐藏面彩蛋 ×5（同人物同画风，≥1024×2048 透明底）

对话有 10% 概率触发角色隐藏面，届时立绘换成彩蛋版。

| ID | 角色 | prompt（人物外观同 B 系列，替换动作/配饰） |
|---|---|---|
| H1 | Haruka | `same manager off-duty, sprawled bonelessly on a cafe sofa in a cardigan over her uniform, snack bag in hand, blissful lazy expression, dreams of doing absolutely nothing` |
| H2 | Momo | `same girl with subtle black-lace gothic accessories, quietly admiring a black rose, soft moody lighting` |
| H3 | Shizuku | `same cook sitting on a small chair surrounded by orphanage children, reading a picture book aloud, unusually gentle open smile` |
| H4 | Suzu | `same girl typing at a terminal with terrifying focus, screens glowing, tiny handheld console in apron pocket` |
| H5 | Aoi | `same trainee in ballet practice wear mid-pirouette in an empty studio at dusk, prodigy-level poise, maid headband still on` |

## G. 乱入客人 ×3（512² 半身，泛用路人）

30% 概率有客人乱入对话，需要三张可复用的路人头像（精细度可低于主角）：

| ID | prompt |
|---|---|
| G1 | `friendly old gentleman customer with a newspaper and reading glasses, half-body` |
| G2 | `energetic college girl customer with a tote bag, half-body` |
| G3 | `tired young office worker customer with loosened tie, half-body` |

## M. 其他

**M1 Momo Q版 chibi（512² 透明底）**
`chibi version of the pink twin-tail waitress, super-deformed cute style,
holding a tiny coffee cup, waving`
用于每日提醒通知的配图与宣传贴纸。
