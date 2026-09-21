# maidcafe ☕

Personal language-listening service, maid-café style: it remembers exactly
which words you know, and brews fresh conversation just for you.

一个"认识你"的英语听力工具。先用**听音优先**的校准摸清你的真实词汇量
（区分"听得出"和"只看字认识"），再用**本地 LLM** 把你该复习的词，实时编进
一间女仆咖啡厅的日常对话——逐词校验，保证周边词汇 90%+ 落在你的已知范围内
（Krashen 可理解输入），配开源 TTS 双音色朗读。全部本地运行，数据不出你的电脑。

## 现在就能用的（v1–v3 已实现）

- **校准**：8,900+ 词按考纲梯度切成 100 词/块，两键节奏（Space/J/K）快速过词，
  实测手速估算剩余时间
- **学习闭环**：生词池 → 复习梯子（1/3/7/15/30 天）→ 毕业进已知库；
  "复习一次" = 完整听完一段带着这个词的**全新对话**
- **对话生成**：generate → verify → repair 闭环——LLM 写、纯代码校验已知占比、
  违规回喂重写；五位性格各异的女仆 + 10% 触发的隐藏面 + 30% 乱入客人
- **听力室**：逐轮揭示 / 纯听模式、生词红标、点任意词查释义并收进生词本、
  点词自动暂停、今日任务一键生成
- **TTS**：Kokoro-82M（本地、盲测比肩商业 API）；macOS `say` 作零依赖备胎

## 快速开始

核心零依赖，Python 3.9+ 即可：

```bash
# 1. 自备 Anki 词库（.apkg）放进 decks/
# 2. 启动
python3 server.py
# 3. 打开 http://localhost:8770 开始校准
```

### 完整体验（对话生成 + 高质量 TTS）还需要：

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

## 按键（校准页）

| 键 | 听发音后 | 显示词后 |
|---|---|---|
| `Space` | 听出来了 | 我会读 |
| `J` | 没听出来 | 我不会读 |
| `K` | 重听 | 重听 |

两下都"会" = 认识；沾一个 J = 进生词本。鼠标点按钮完全等效。

## 项目结构

```
server.py      # stdlib HTTP 服务 + SQLite（校准/调度/生词本全部接口）
deckparse.py   # .apkg 词库解析（zip + SQLite + 媒体清单）
dialogue.py    # 对话生成闭环（Ollama + 校验器 + 修复循环 + TTS 调度）
tts_kokoro.py  # Kokoro 合成 worker（跑在 .venv-tts 里）
roster.json    # 女仆角色库（人设卡 + 隐藏面 + 音色映射）
scenes.json    # 场景与乱入概率
static/        # 校准页 + 听力室（vanilla JS，无框架）
PLAN.md        # 产品与商业决策
DESIGN_BRIEF.md# 设计交接（含外包画稿 prompts）
```

## 设计原则

**不考试**（从不弹窗逼你打分，考试由你主动发起）· **不倍速**（自然语速是
训练的一部分）· **不催**（不打卡不连胜不催学，躺平是客人的权利）·
**本地优先**（数据永远在你机器上）· **每次复习都是新场景**（编码变异 >
重复例句——这是本地 LLM 给的独门武器）

## License

AGPL-3.0 · 词库与词典数据（ECDICT）、TTS 模型（Kokoro）各按其原始协议，
不随本仓库分发。
