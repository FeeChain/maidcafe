# maidcafe ☕ — 设计交接文档

> 交给 design：请基于本文档做**全站视觉设计**。功能与接口已全部实现并冻结，
> 设计不改变功能结构。需要插画的位置**不要自己画**——按第 6 节的 prompt 清单
> 标注占位，最终画稿由外部完成后替换。

## 1. 项目初心

一个"认识你"的英语听力工具。起点是一个真实痛点：许多中国学习者（包括作者本人，
词汇量约 8000）**看词全认识、听音对不上**——传统背单词软件用卡片喂眼睛，
不喂耳朵。

我们的解法建立在两条被验证的语言习得原理上：
- **可理解输入**（Krashen）：新词必须出现在 90–98% 已知词汇的语境里才能被习得。
  我们用本地 LLM 把每个用户的生词，实时编进只用 TA 已知词汇的对话——逐词校验，
  不达标就重写。
- **Narrow listening**：固定的角色、固定的场景，让背景词汇天然重复。
  这就是女仆咖啡厅主题的**功能性**：五位性格各异的女仆是"熟人"，
  你的生词在她们的日常里一次次重逢。

女仆咖啡厅的服务精神——记住每位熟客的口味、端上专属的那一杯——
恰好就是产品机制本身：记住你认识哪些词，为你现做每一段听力。

原则（设计中必须体现的品格）：
- **不考试**：从不弹窗逼用户打分。学没学会用户自己知道，工具只把信息摆全。
- **不倍速**：自然语速是听力训练的一部分。
- **本地优先**：全部数据在用户机器上，桌面版永久免费开源。
- **两键节奏**：校准全程只用 Space/J/K，手不离键盘。

## 2. 用户

中文母语的英语学习者。第一用户画像：有一定词汇量（四级以上）、
听力落后于阅读、想利用碎片时间、对二次元文化有好感或不排斥。

## 3. 页面与功能清单（已全部实现）

### 3.1 校准页 `/`
摸清用户真实词汇量（区分"听得出"与"只看字认识"）。
- 词库按考纲梯度排成 90 块 × 100 词（中考→高考→四级→六级→考研→托福→GRE→考纲外），块内乱序
- 块选择器（显示段位+进度）、词库筛选、模式筛选（未标记/全部）
- 卡片两段式：先只放发音（大喇叭按钮）→ Space 听出来了 / J 没听出来 →
  显示词形+音标+释义 → Space 我会读 / J 我不会读 → 自动下一词
- 顶部统计条：本块进度、认识/生词计数、按实测手速估算的剩余时间
- 结束本轮按钮、块完成结算页（→ 进入下一块）、可关闭的按键提示条
- 欢迎页（"欢迎回来，主人 ☕"+ 按键说明）

### 3.2 听力室-列表 `/listen`
- **今日任务按钮**（核心 CTA）：到期复习词+新词配额 → 自动生成今日对话
- 状态行：到期复习 N · 生词池 N · 学习中 N · 已毕业 N
- 自选生成（手动挑词）
- 对话卡片列表：编号/日期/轮数/出场角色/场景/目标词 chips
- 生成中状态提示（"好一段先听一段"）

### 3.3 听力室-播放器
- 信息区：场景标题、目标词 chips（词+迷你释义，可点开释义卡）、
  已知占比徽章（"周边词汇 100% 在你的已知范围内"）
- 控制排：播放/暂停（空格）、上一轮/下一轮、循环开关、
  字幕三模式（纯听/逐轮揭示/全文）、删除
- 字幕区：说话人名+专属颜色、当前轮高亮、未播轮遮罩（●●●）、
  **目标生词红色**、**任意单词可点**→释义卡
- 释义卡（浮层）：词、音标、释义、单词发音按钮、
  非生词时显示"＋加入生词本"
- 完整听完一遍自动上报复习（用户无感知）

### 3.4 生词本
- 手动加词输入框（词典校验）
- 学习中/生词池 区：每词=词/音标/发音/梯级徽章（生词池｜第N级·X天后｜今日到期）/
  出现过的对话编号/我学会了/还不熟/首行释义
- 已毕业区：词+重新学按钮（毕业词会作为背景词汇继续在对话里出现）

### 3.5 学习机制（设计需要理解的隐形逻辑）
词的三态：生词池 →（进入今日任务）→ 学习中（复习梯子 1/3/7/15/30 天，
"复习"=完整听完包含它的**全新**对话）→ 已毕业（进入已知库，作背景词）。
每次复习都是**新场景**——这是产品招牌，也是设计叙事上可以强调的点
（"女仆们又聊起了那个词"）。

## 4. API 参考（已冻结）

| 方法 | 路径 | 参数 | 返回 |
|---|---|---|---|
| GET | `/api/words` | deck, tier, mode | 校准词队列 |
| GET | `/api/stats` | deck, tier | 计数+实测手速+剩余估时 |
| GET | `/api/tiers` | deck | 90 块的进度与段位范围 |
| GET | `/api/decks` | - | 词库名列表 |
| POST | `/api/mark` | {word, status:1/2/3/null} | 校准标记 |
| GET | `/audio/<word>` | - | 单词发音 mp3 |
| GET | `/api/dialogues` | - | 对话列表 |
| GET | `/api/dialogue/<id>` | - | 对话全文+目标词释义+音频文件列表 |
| GET | `/dialogue_audio/<id>/<file>` | - | 对话逐轮音频 wav |
| POST | `/api/generate` | {words[]} 或 {auto:N} | 触发生成（异步） |
| POST | `/api/daily_task` | {new_quota:5} | 今日任务：分包并批量生成 |
| POST | `/api/listened` | {id} | 上报完整听完→目标词爬梯 |
| GET | `/api/daily_status` | - | {due, backlog, learning, graduated} |
| GET | `/api/wordbook` | - | {learning[], graduated[]}（含梯级/到期） |
| GET | `/api/lookup` | word | 任意词查询（音标/释义/是否已在库） |
| POST | `/api/wordbook_add` | {word} | 手动加词 |
| POST | `/api/word/learned` | {word} | 手动毕业 |
| POST | `/api/word/unfamiliar` | {word} | 打回梯底 |
| POST | `/api/word/readd` | {word} | 毕业词重新学 |
| POST | `/api/dialogue_delete` | {id} | 删除对话 |

## 5. 视觉方向

**日式二次元（现代 TV 动画质感），暖咖啡厅色调。**

- 现有色板（可优化但保持暖调）：奶油底 `#F6F1E7`、卡片米白 `#FFFDF8`、
  咖啡棕主色 `#A4632E`、墨棕文字 `#3A2F28`、红（生词）`#C0574F`、
  绿（认识）`#5F8F57`、琥珀（生词池）`#C08A2D`
- 气质关键词：温暖、轻快、可爱但不幼稚、有"店"的空间感
- 角色元素应出现在：欢迎页、空状态、生成等待、完成庆祝、每日提醒文案
- 中文为主界面语言，学习内容为英文；注意中英混排的字体与字号节奏
- 键盘提示（kbd 样式）是交互身份的一部分，保留并设计好看

## 6. 美术资产清单（外包绘画用 · design 只做占位与排版）

> ⚠️ 本节已扩充并独立成 **ART_ASSETS.md**（含官网 hero、图标衍生、隐藏面全员、
> 客人头像与优先级表）——发画师以那份为准，本节仅留存设计排版参考。

> 所有 prompt 已写好可直接投喂画师或生图模型。
> **通用风格块**（每条 prompt 前置）：
> `clean modern Japanese anime style, 2020s TV anime key-visual quality,
> soft cel shading, warm cozy cafe lighting, cream and coffee-brown pastel
> palette, crisp line art, cheerful slice-of-life mood, no text, no watermark,
> high resolution`

### 6.1 角色立绘 ×5（全身立绘 PNG 透明底 ≥1024×2048 + 半身头像 512²）

**Haruka（遥，26，店长）** — 用于：店长相关状态、结算页
`26-year-old cafe manager, long straight dark-navy hair in a low ponytail,
gentle tired amber eyes, elegant burgundy long-skirt maid dress with a white
long apron, small silver pocket-watch chain, holding a clipboard, calm faint
smile with a hint of a sigh, mature graceful posture`

**Momo（莓莓，20，看板娘）** — 用于：欢迎页主视觉、每日提醒
`20-year-old star waitress, strawberry-pink twin-tails with star hairpins,
big sparkling magenta eyes, bright classic maid outfit with extra frills and
a heart-shaped apron pocket, winking and giving a cheerful welcome pose,
radiating energy` （隐藏面彩蛋版：同一人物换 subtle black-lace gothic
accessories, quietly admiring a black rose）

**Shizuku（雫，22，后厨担当）** — 用于：生成等待页（"烹制对话中"）
`22-year-old kitchen cook, silver-grey blunt short bob, half-lidded teal
eyes, deadpan minimal expression, dark-green tea apron over a rolled-sleeve
shirt, kitchen headscarf, carrying a tray with perfect effortless posture,
tiny hidden warmth in her look`

**Suzu（铃，19，大厅女仆）** — 用于：错误页/404（打翻了盘子）
`19-year-old clumsy floor maid, messy orange side-ponytail, round hazel
eyes, small band-aid on cheek, slightly oversized maid uniform with a
crooked headband, balancing a wobbling stack of teacups, flustered but
cheerful expression` （隐藏面彩蛋版：same girl typing at terminal with
terrifying focus, tiny handheld console in apron pocket）

**Aoi（葵，18，实习生）** — 用于：校准页引导、新手引导
`18-year-old earnest trainee maid, neat black bob with a plain white
headband, sincere violet eyes, trainee ribbon badge, holding a notebook and
pencil, standing perfectly straight with unconscious ballet-like grace,
slightly nervous polite smile`

### 6.2 状态插画（横幅 1024×640 左右，衬奶油底）

| 用途 | 内容 prompt（接通用风格块） |
|---|---|
| 欢迎页 | `Momo at the cafe front door holding it open, warm light spilling out, "welcome back" gesture, cozy cafe interior behind` |
| 空列表 | `an empty cafe table by the window, one steaming coffee cup, soft afternoon light, quiet and inviting` |
| 生成等待 | `Shizuku in the kitchen calmly cooking, steam rising, ingredients floating like little words around the pot` |
| 全部完成庆祝 | `all five maids cheering together in the cafe hall, confetti, warm celebration` |
| 错误/404 | `Suzu mid-trip with flying teacups frozen in air, comically panicked, other maids reaching to catch the cups` |

### 6.3 场景背景 ×4（16:9，柔焦，播放器页头用）

`cafe main hall in warm afternoon light` ·
`cafe hall on a rainy evening, rain on the window, lamps glowing` ·
`cafe kitchen before opening, neat and quiet` ·
`tiny manager's office with schedule board and piled receipts`

### 6.4 标识

Logo/favicon：`circular badge logo, a coffee cup wearing a tiny maid
headband ribbon, coffee-brown on cream, simple enough to read at 32px`

## 7. 交付物要求（对 design）

1. 四个页面（校准/列表/播放器/生词本）+ 欢迎页 + 各状态页的完整布局稿
2. 插画位置全部用灰框占位并标注对应 6.x 资产编号
3. 色板/字体/组件规范（按钮、chips、徽章、释义卡、kbd 键帽）
4. 桌面优先（本地 web app），但布局需为未来手机 PWA 预留纵向适配思路
