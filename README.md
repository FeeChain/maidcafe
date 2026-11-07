<div align="center">

<img src="static/art/A1_logo.png" width="130" alt="maidcafe logo">

# maidcafe ☕

**一间记得你认识哪些单词的女仆咖啡厅。**

背了几千个单词，还是听不出、拼不对？<br>
maidcafe 把你想学的词，<br>
现场编成一段只属于你的咖啡厅日常对话——全部在你自己的电脑上完成。

[![CI](https://github.com/FeeChain/maidcafe/actions/workflows/ci.yml/badge.svg)](https://github.com/FeeChain/maidcafe/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Local First](https://img.shields.io/badge/data-100%25%20local-brightgreen)
![License](https://img.shields.io/badge/license-AGPL--3.0-orange)

<img src="static/cafe/window-seat.jpg" width="820" alt="欢迎光临">

</div>

---

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

<div align="center">
<img src="static/art/C2_empty.png" width="720" alt="窗边的空桌">
</div>

## 店里的规矩

> **自主回想**（由你发起，从不弹窗逼你打分）· **不倍速**（自然语速就是训练）·
> **不催**（不打卡、不连胜、不推送，躺平是客人的权利）· **不累计**（没有"欠了
> 三天的任务"，每次打开都是新的一份）· **关掉就是收工**（不点任何按钮直接关，
> 每次已确认的回想都已保存，尚未提交的判断会留给下次）

## 店员

<img src="static/art/B2_momo_full.png" width="230" align="right" alt="Momo">

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

核心**零依赖**，Python 3.9+ 即可跑起来：

```bash
# 启动后打开 http://localhost:8770
python3 server.py
```

项目已附带「窗边的第一杯」24 词入门包，含原创中英释义/例句与合成录音。无 Ollama 时仍可试听和翻卡。下载入口在窗边菜单与设置页，标准 `.apkg` 也可导入 Anki，制作说明见 [resources/README.md](resources/README.md)。

自己的 `.apkg` 放进 `decks/`，重启后加载。新增、替换同名包或移除包都会更新缓存。已有的个人词库与学习记录无需搬迁。

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
