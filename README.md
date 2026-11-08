<div align="center">

<img src="static/art/A1_logo.png" width="130" alt="maidcafe logo">

# maidcafe ☕

**[下载 Mac / Windows 桌面版](https://github.com/FeeChain/maidcafe/releases)** <!-- desktop-download-cta -->

**一间记得你认识哪些单词的女仆咖啡厅。**

背了几千个单词，还是听不出、拼不对？<br>
maidcafe 把你想学的词，<br>
现场编成一段只属于你的咖啡厅日常对话——全部在你自己的电脑上完成。

[![构建与发布](https://github.com/FeeChain/maidcafe/actions/workflows/pipeline.yml/badge.svg)](https://github.com/FeeChain/maidcafe/actions/workflows/pipeline.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Local First](https://img.shields.io/badge/data-100%25%20local-brightgreen)
![License](https://img.shields.io/badge/license-AGPL--3.0-orange)

<img src="static/cafe/scenes/window-seat-v3.webp" width="820" alt="欢迎光临">

</div>

---

<!-- desktop-downloads:start -->
## 下载桌面版

**[点击这里下载最新 Mac / Windows 安装包](https://github.com/FeeChain/maidcafe/releases)**

| 你的电脑 | 在最新发布页选择的文件 |
|---|---|
| Mac M 系列 | 文件名以 `macOS-arm64.dmg` 结尾 |
| Intel Mac | 文件名以 `macOS-x86_64.dmg` 结尾 |
| Windows 64 位 | 文件名以 `Windows-x64-Setup.exe` 结尾 |

安装包约 20–25 MB，发布页顶部有各系统的直接下载按钮。无需 Python 或命令行。先体验内置词卡和试听，生成自己的故事只需在软件内点「故事设置 → 一键准备」；引擎和模型会自动下载、校验和配置，支持暂停续传。轻量模型约 1.4 GB、标准约 2.5 GB，首次还需下载引擎；自动准备需要 macOS 14+ / Windows 10 22H2+。当前为未完成发行签名的预览版，首次打开可能出现系统来源提示；[安装说明与更新记录](https://github.com/FeeChain/maidcafe/releases)。
<!-- desktop-downloads:end -->

人物与配图：[当前定妆规范](design/characters/v1/使用说明.txt) · [素材与提示词](static/cafe/README.md)。

## 它解决什么问题

大多数背单词软件在**考你**；maidcafe 在**陪你听**。

- **"看得懂，听不出"**——传统软件只测"认不认识字形"。这里的校准是听音优先：
  先放发音，你判断听没听出来，再看词形判断能否想起词义。两个词汇量，分开算。
- **"例句永远那两句"**——每次复习，你的生词都被现场编进一段**全新的**对话。
  同一个词，昨天出现在雨夜的打烊闲聊里，今天出现在店长核对排班的办公室里。
- **"数据在别人服务器上"**——LLM、TTS、词库、学习记录，全部本地。
  不联网也能用，你的学习数据永远不出你的电脑。

## 怎么玩

**① 入座**：欢迎页说明玩法，窗边菜单有一段可以离线播放的招待对话。无需先测词汇量，也不用先下载词库。

**② 点单**：输入 1–5 个英文词或短语，让女仆们把它们编进日常故事。也可以先翻内置词卡，翻开的词自动攒进下一杯对话，1 个词就能开始。

**③ 跟听**：本地 Ollama 写稿，代码检查目标词覆盖和周边词难度，不合格时尝试重写。遗漏目标词的稿件会停止并提示重试。配音后逐轮听、逐轮揭晓，点词查看释义。词义是否自然准确仍取决于模型，自动校验不能替代内容抽查。

**④ 回想**：自己决定什么时候回想，只出本次见过的词。先想意思，再揭晓，选择「想起来了」或「还想再听」。保存成功后才前进，已通过的词进入间隔复习。每份数量由你定，无打卡和连续天数要求。

可选的「调一调听力难度」先问听音，再问看词，分别记录。无录音的词只测阅读，不生成听力成绩。

迎宾、学习、听故事与休息各有三种场景，进入阶段时轮换，翻词和播放中保持静止。设置里的「店里的风景」可以选择固定配图或安静阅读。五位店员的完整立绘与场景图随安装包提供，离线也能看到。

<div align="center">
<img src="static/cafe/scenes/rainy-table.webp" width="720" alt="窗边的空桌">
</div>

## 店里的规矩

> **自主回想**（由你发起，从不弹窗逼你打分）· **不倍速**（自然语速就是训练）·
> **不催**（不打卡、不连胜、不推送，躺平是客人的权利）· **不累计**（没有"欠了
> 三天的任务"，每次打开都是新的一份）· **关掉就是收工**（不点任何按钮直接关，
> 每次已确认的回想都已保存，尚未提交的判断会留给下次）

## 店员

<img src="static/cafe/cast/momo-full-v3.webp" width="230" align="right" alt="Momo">

五位性格各异的女仆轮班：沉稳的店长、招牌店员 **Momo**（右图）、
毒舌的后厨、冒失的新人、认真的实习生。

- 每场对话按**人数纪律**随机成局（双人日常最多，全员到齐是稀有场面）
- 每位女仆都有 **10% 概率触发的隐藏面**——某天你会听到平时元气的
  Momo 突然安静下来
- 30% 概率有**熟客来店**：嘴硬心软的 Old Tom、每次点同一杯的上班族 Mr. Sato、
  话特别多的 Anna……五位熟客性格和声音都固定，越听越熟
- 场景库涵盖大厅、雨夜、后厨、办公室，同词不同景

角色人设、场景与乱入概率都在 `roster.json` / `scenes.json`，改起来就是改 JSON。

<br clear="right">

## 快速开始

维护者更新与发布流程见 [RELEASING.md](RELEASING.md)：PR 自动测试与打包，版本升级合入 main 后自动验证并发布。

### 桌面预览：Mac 与 Windows

桌面版使用独立窗口，内置 Python、界面、入门词库和试听录音。Mac 打开 `.dmg` 后拖入 Applications；Windows 运行 `Windows-x64-Setup.exe` 按向导安装。从开始菜单/应用程序打开即可，无需终端。

安装包在 [GitHub Releases](https://github.com/FeeChain/maidcafe/releases) 公开下载，无需 GitHub 账号。提供 Mac Apple Silicon、Mac Intel、Windows x64。当前为未完成签名/公证的预览版。

第一次可以直接听招待、翻词卡。想生成自己的故事，在「故事设置」点「一键准备」：软件下载官方 Ollama 引擎、校验文件、下载模型、试运行，成功后自动配置。可暂停并续传，已有本地 Ollama 会复用；进阶设置仍可选择自己的模型。不需要自己装引擎、敲命令或填写密钥。

轻量模型约 **1.4 GB**，标准模型约 **2.5 GB**；引擎首次下载 Mac 约 **186 MB**、Windows 约 **1.6 GB**。自动准备需要 macOS 14+ 或 Windows 10 22H2+，建议至少 8 GB 内存；低于 16 GB 默认推荐轻量助手。下载前显示大小并检查磁盘空间。下载后可离线使用，首次写故事及 CPU 运行可能较慢。引擎来自 [Ollama 官方发行](https://github.com/ollama/ollama/releases)，模型来自官方模型库。

Mac/Windows 优先使用已配置的 Kokoro，否则使用系统英语语音；没有可用配音时仍可阅读故事。

设置中的「词库与学习记录」支持导入 Anki 词包、导出记录，在没有学习记录的安装中恢复备份。备份包含进度和故事文字，不含词库、模型或录音。Mac 数据目录是 `~/Library/Application Support/maidcafe/`，Windows 是 `%LOCALAPPDATA%\maidcafe\`；替换应用不会覆盖记录。Windows 需要 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。

维护者构建：Python 3.12 环境安装 `requirements-desktop.txt`，运行 `python packaging/build_desktop.py`；Windows 另需 Inno Setup 6。验证实际程序可运行 `python packaging/smoke_desktop.py <可执行文件路径>`。发布前完成签名、公证，并抽查生成内容。

### 从源代码运行

核心**零依赖**，Python 3.9+ 即可跑起来：

```bash
# 启动后打开 http://localhost:8770
python3 server.py
```

项目已附带「窗边的第一杯」24 词入门包，含原创中英释义/例句与合成录音。无 Ollama 时仍可试听和翻卡。下载入口在窗边菜单与设置页，标准 `.apkg` 也可导入 Anki，制作说明见 [resources/README.md](resources/README.md)。

自己的 `.apkg` 可在设置中导入，也可放进 `decks/`，重启后加载。新增、替换同名包或移除包都会更新缓存。源代码版已有的个人词库与学习记录仍使用原路径；迁移到桌面版可导出记录再恢复。

### 完整体验（对话生成 + 高质量 TTS）还需要

```bash
# 本地 LLM（对话生成引擎）
ollama list  # 找到本机可用模型的完整名称
# 把下面的名称替换成 list 中的实际名称，再启动
MAIDCAFE_MODEL="你的模型名称" python3 server.py

# 词频/考纲数据（难度分块 + 词形还原用）
#   下载 ECDICT sqlite 版，解压出 stardict.db 放到 data/
#   https://github.com/skywind3000/ECDICT/releases

# 词根词缀表（可选；同为 ECDICT 项目，MIT。不装则释义卡不显示词根）
curl -L -o data/wordroot.txt https://raw.githubusercontent.com/skywind3000/ECDICT/master/wordroot.txt

# Kokoro TTS（可选但强烈建议；不装则回落 macOS say）
uv venv --python 3.12 .venv-tts
uv pip install --python .venv-tts/bin/python kokoro-onnx soundfile
#   下载 kokoro-v1.0.onnx 与 voices-v1.0.bin 放到 data/
#   https://github.com/thewh1teagle/kokoro-onnx/releases
```

## 按键与鼠标

| 场景 | 操作 |
|---|---|
| 学习词卡 | Space 显示，再按下一张，K 重听 |
| 主动回想 | Space 揭晓释义，再用 F「想起来了」或 J「还想再听」 |
| 可选校准 | F 肯定、J 否定，先听音再看词，K 重听 |
| 输入框、按钮 | 使用原生键盘行为，Tab 移动焦点，Space/Enter 激活已聚焦按钮 |
| 弹窗 | Tab 在弹窗内移动，Esc 关闭并回到原控件 |

无录音只判断阅读。鼠标点按钮和键盘操作结果一致。

## 引擎盖下面

- **从边界外扩**：8,900+ 词按考纲段位 + 词频排成一条线、切成 100 词的块。
  探针定位你的边界块之后，边界内=已知，新词严格按难度从边界向外供给——
  你学的每个词都是"踮脚够得着"的那个。
- **generate → verify → repair**：LLM 负责写，**纯代码**负责验（目标词齐不齐、
  周边词汇已知占比、人数纪律），不合格把违规项喂回去重写，最多四稿取最优。
- **复习听的是全新对话**：不是把例句再放一遍，而是让这个词在新语境里
  再遇见你一次（编码变异优于机械重复——这是本地 LLM 才给得起的独门武器）。
- **测试**：120 个自动化用例四层覆盖（单元 / 对话管线 / HTTP 契约 / Playwright
  真浏览器全点击），双系统双 Python 版本 CI。

## 项目结构

```
server.py      # stdlib HTTP 服务 + SQLite（校准/会话/生词本全部接口）
deckparse.py   # .apkg 词库解析（zip + SQLite + 媒体清单）
dialogue.py    # 对话生成闭环（Ollama + 校验器 + 修复循环 + TTS 调度）
tts_kokoro.py  # Kokoro 合成 worker（跑在 .venv-tts 里）
roster.json    # 女仆角色库（人设卡 + 隐藏面 + 音色映射）
scenes.json    # 场景与乱入概率
static/        # 主页 + 校准页 + 听力室（vanilla JS，无框架）
FLOW.md        # 产品流程宪法（状态机 + 不变量）
tests/         # 四层自动化测试
```

## 路线图

- [x] 探针式词汇量测定（动态折半 + 盲测档案）
- [x] 开门即学的主流程（现抓一份 · 篮子煮对话 · 考试落库）
- [ ] 画稿全量上线（首批已就位，持续更新中）
- [ ] 统计页 · 词表导入导出 · 纯文本词库
- [ ] 跨平台打包（桌面免费）
- [ ] Web 版（无 LLM 依赖的轻量线上版）

## License

AGPL-3.0 · 词库与词典数据（ECDICT）、TTS 模型（Kokoro）各按其原始协议，
不随本仓库分发。

<div align="center">
<sub>☕ 欢迎光临，客人。今天也请慢用。</sub>
</div>
