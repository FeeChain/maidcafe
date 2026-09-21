<div align="center">

<img src="static/art/A1_logo.png" width="130" alt="maidcafe logo">

# maidcafe ☕

**一间记得你认识哪些单词的女仆咖啡厅。**

背了几千个单词，还是听不出、拼不对？<br>
maidcafe 先摸清你的真实听力词汇量，再把你正在学的词，<br>
现场编成一段只属于你的咖啡厅日常对话——全部在你自己的电脑上完成。

[![CI](https://github.com/FeeChain/maidcafe/actions/workflows/ci.yml/badge.svg)](https://github.com/FeeChain/maidcafe/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Local First](https://img.shields.io/badge/data-100%25%20local-brightgreen)
![License](https://img.shields.io/badge/license-AGPL--3.0-orange)

<img src="static/art/C1_welcome.png" width="820" alt="欢迎光临">

</div>

---

## 它解决什么问题

大多数背单词软件在**考你**；maidcafe 在**陪你听**。

- **"看得懂，听不出"**——传统软件只测"认不认识字形"。这里的校准是听音优先：
  先放发音，你判断听没听出来，再看词形判断会不会读。两个词汇量，分开算。
- **"例句永远那两句"**——每次复习，你的生词都被现场编进一段**全新的**对话。
  同一个词，昨天出现在雨夜的打烊闲聊里，今天出现在店长核对排班的办公室里。
- **"数据在别人服务器上"**——LLM、TTS、词库、学习记录，全部本地。
  不联网也能用，你的学习数据永远不出你的电脑。

## 怎么玩

**① 测**：动态折半探针，2–3 分钟定位你的词汇边界（精确到 100 词一块），
听力口径和阅读口径分开报告，带置信区间。支持盲测存档、多次测定自选采用。

**② 学**：打开就是为你现抓的一份词（到期复习 + 新词，难度紧贴你的边界外沿）。
翻卡听音、乱序过一遍；翻开的词自动攒进"下一杯"——攒够 5 个（1 个也行），
让女仆们现煮一场以这些词为目标的对话。

**③ 听**：本地 LLM 写稿 → 纯代码逐词校验（周边词汇 90%+ 必须落在你的已知
范围内，Krashen 可理解输入）→ 不合格自动回炉重写 → 开源 TTS 双音色配音。
逐轮揭示跟听，点任意词查释义、收生词，点词自动暂停。

**④ 过**：考试永远由你主动发起，双 Space 通过才落库——复习梯 1/3/7/15/30 天，
爬完毕业。挂了零惩罚，没有小红点，没有连胜焦虑。

<div align="center">
<img src="static/art/C2_empty.png" width="720" alt="窗边的空桌">
</div>

## 店里的规矩

> **不考试**（考试由你发起，从不弹窗逼你打分）· **不倍速**（自然语速就是训练）·
> **不催**（不打卡、不连胜、不推送，躺平是客人的权利）· **不累计**（没有"欠了
> 三天的任务"，每次打开都是新的一份）· **关掉就是收工**（不点任何按钮直接关，
> 一分学习记录都不丢——因为唯一的落库就是你考过的那一下）

## 店员

<img src="static/art/B2_momo_full.png" width="230" align="right" alt="Momo">

五位性格各异的女仆轮班：沉稳的店长、招牌店员 **Momo**（右图）、
毒舌的后厨、冒失的新人、认真的实习生。

- 每场对话按**人数纪律**随机成局（双人日常最多，全员到齐是稀有场面）
- 每位女仆都有 **10% 概率触发的隐藏面**——某天你会听到平时元气的
  Momo 突然安静下来
- 30% 概率有**客人乱入**：常客老爷爷、赶稿的上班族、放学的学生……
- 场景库涵盖大厅、雨夜、后厨、办公室，同词不同景

角色人设、场景与乱入概率都在 `roster.json` / `scenes.json`，改起来就是改 JSON。

<br clear="right">

## 快速开始

核心**零依赖**，Python 3.9+ 即可跑起来：

```bash
# 1. 自备 Anki 词库（.apkg）放进 decks/
# 2. 启动
python3 server.py
# 3. 打开 http://localhost:8770，先测词汇量，然后直接开始学
```

### 完整体验（对话生成 + 高质量 TTS）还需要

```bash
# 本地 LLM（对话生成引擎）
ollama pull qwen3.6:27b   # 或任意你机器带得动的模型，环境变量 MAIDCAFE_MODEL 指定

# 词频/考纲数据（难度分块 + 词形还原用）
#   下载 ECDICT sqlite 版，解压出 stardict.db 放到 data/
#   https://github.com/skywind3000/ECDICT/releases

# Kokoro TTS（可选但强烈建议；不装则回落 macOS say）
uv venv --python 3.12 .venv-tts
uv pip install --python .venv-tts/bin/python kokoro-onnx soundfile
#   下载 kokoro-v1.0.onnx 与 voices-v1.0.bin 放到 data/
#   https://github.com/thewh1teagle/kokoro-onnx/releases
```

## 两个键就够了

| 键 | 听发音后 | 显示词后 |
|---|---|---|
| `Space` | 听出来了 | 我会读 |
| `J` | 没听出来 | 我不会读 |
| `K` | 重听 | 重听 |

两下都"会" = 认识；沾一个 `J` = 进生词本。考试同款按键。鼠标点按钮完全等效。

## 引擎盖下面

- **从边界外扩**：8,900+ 词按考纲段位 + 词频排成一条线、切成 100 词的块。
  探针定位你的边界块之后，边界内=已知，新词严格按难度从边界向外供给——
  你学的每个词都是"踮脚够得着"的那个。
- **generate → verify → repair**：LLM 负责写，**纯代码**负责验（目标词齐不齐、
  周边词汇已知占比、人数纪律），不合格把违规项喂回去重写，最多四稿取最优。
- **一次复习 = 一场完整对话**：不是把例句再放一遍，而是让这个词在新语境里
  再遇见你一次（编码变异优于机械重复——这是本地 LLM 才给得起的独门武器）。
- **测试**：66 个自动化用例四层覆盖（单元 / 对话管线 / HTTP 契约 / Playwright
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
