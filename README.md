<div align="center">

# MaidCafe

**一杯咖啡，一组单词，姐姐们的一段小故事。**

在女仆咖啡馆里学英语。翻开词卡，把想学的词交给本地 AI，听它们出现在新的日常对话中。

[**下载 Mac / Windows**](https://github.com/FeeChain/maidcafe/releases) · [看看怎么玩](#从入座到下一杯咖啡) · [单词与复习原理](design/WORD_LIFECYCLE.md)

<img src=".github/assets/welcome.webp" width="960" alt="MaidCafe 欢迎页：Suzu 在咖啡馆门口端着咖啡迎接你">

[![构建与发布](https://github.com/FeeChain/maidcafe/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/FeeChain/maidcafe/actions/workflows/pipeline.yml) [![Release](https://img.shields.io/github/v/release/FeeChain/maidcafe?include_prereleases&label=桌面版&color=835d4c)](https://github.com/FeeChain/maidcafe/releases) [![AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-bb9672)](LICENSE)

</div>

## 下载，入座

<!-- desktop-downloads:start -->
| 你的电脑 | 下载 0.4.0 预览版 |
|---|---|
| Mac · Apple Silicon / M 系列 | [下载 DMG · 426 MB](https://github.com/FeeChain/maidcafe/releases/download/v0.4.0-preview/maidcafe-0.4.0-preview-macOS-arm64.dmg) |
| Mac · Intel | [下载 DMG · 435 MB](https://github.com/FeeChain/maidcafe/releases/download/v0.4.0-preview/maidcafe-0.4.0-preview-macOS-x86_64.dmg) |
| Windows · 64 位 | [下载安装程序 · 389 MB](https://github.com/FeeChain/maidcafe/releases/download/v0.4.0-preview/maidcafe-0.4.0-preview-Windows-x64-Setup.exe) |

**无需 Python、终端或 API 密钥。** Mac 打开 DMG 后拖入 Applications；Windows 按安装向导操作。

安装包内置 **21,244 词基础词库、25 张咖啡馆背景和 Kokoro 英语配音**。安装后就能测试、听词和学习。AI 故事助手在软件内「左下角菜单 → 设置 → 查看助手 → 一键准备」下载并配置，已有本地 Ollama 也可直接选用。

轻量故事模型约 1.4 GB，标准约 2.5 GB；首次下载引擎另需 Mac 约 186 MB / Windows 约 1.6 GB。准备完成后可离线运行。Mac 需 macOS 14+，Windows 建议 Windows 10 22H2+ / Windows 11，并安装 [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)。

当前仍为预览版，尚未完成 Apple Developer ID 公证和 Windows 发行签名，首次打开可能出现来源提示。操作方法、文件大小与 SHA-256 见 [发布页](https://github.com/FeeChain/maidcafe/releases) 和包内《开始使用》。
<!-- desktop-downloads:end -->

## 从入座到下一杯咖啡

**认识彼此** → **找到起点** → **五词体验** → **一组学习** → **听一段故事，或继续下一组**

第一次可以选择自己已经熟练掌握的词汇档位，也可以做二分、抽样或完整测试。选择 CET4 表示已经掌握四级词汇，之后从 CET6 开始。测试随时保存续接。

正式学习默认每组 20 个词，先过到期复习，再学新词。先听、翻开，再选「学会了」或「再学一次」。没记住的词留下重学，20 个可以逐渐变成 5 个、1 个。整组都学会后，就能继续。

<img src=".github/assets/learning.webp" width="960" alt="MaidCafe 学习页：左侧咖啡馆场景、右侧词卡和四个胶囊按钮">

**想听这个词怎么用，就生成一段对话。** 单词下方可以生成只围绕当前目标词的短对白；组末可以随机选 3 / 5 词，或自己勾选最多 5 词。剩几个就用几个，每次生成都保留，可反复听。生成和播放均由你决定。

英文随播放显示，目标词高亮，点词可查释义。配音统一使用 Kokoro 英音／美音。词库、按天整理的对话历史、设置与主动考试，都收在左下角菜单里。

<img src=".github/assets/dialogue.webp" width="960" alt="MaidCafe 对话播放器：英文对白随播放显示，单词高亮并可点击查词">

## 一间会记住你的咖啡馆

| 咖啡馆里的体验 | 实际怎么做 |
|---|---|
| 每组换个风景 | 25 张背景，当前组翻卡、重学和重新打开时保持一致 |
| 五位不同的店员 | Momo、Haruka、Shizuku、Suzu、Aoi，各有固定人设、声音与隐藏性格 |
| 新的单词语境 | 本地 AI 根据目标词与已知词范围写稿，检查覆盖和难度，必要时重写 |
| 记住学过的词 | 首次学会进入复习档，按照既有权重模型安排后续复习 |
| 自己决定节奏 | 没有打卡、连胜或催学通知；退出后保留当前词卡和测试进度 |
| 记录留在本机 | 词库、生成、配音与学习数据库都在你的电脑上；支持导入和备份 |

主动考试只查看本次掌握情况，**不改变复习记录**。完整规则、公式、代码入口和与旧设计的差异，请看 [单词生命周期核对](design/WORD_LIFECYCLE.md)。AI 的自然度和词义准确性仍需要内容抽查，程序不会把自动校验当成完整的语义保证。

## 自己的词，也能带进来

在菜单中打开「词库与生词本」，可查词、添加词、导入文字词表或兼容的 Anki `.apkg` 词包。

[原创 24 词入门包](resources/window-seat.apkg) · [词库、模型与素材来源](resources/README.md) · [人物定妆规范](design/characters/v1/使用说明.txt)

学习记录可以从设置中导出，并在没有学习记录的安装中恢复。备份包含学习进度、词卡位置、设置与故事文本；词包、模型和配音文件需要另行保留。

<details>
<summary><strong>本地数据在哪里？</strong></summary>

- Mac：`~/Library/Application Support/maidcafe/`
- Windows：`%LOCALAPPDATA%\maidcafe\`
- 替换应用不会覆盖个人数据目录。

</details>

<details>
<summary><strong>开发与自行构建</strong></summary>

建议使用 Python 3.12 和虚拟环境：

```sh
python -m pip install -r requirements-desktop.txt
python packaging/prepare_speech.py
python desktop.py
```

也可运行 `python server.py`，打开 `http://localhost:8770`。AI 模型可在界面中准备；源代码启动时可通过 `MAIDCAFE_MODEL` 选择现有模型。完整 ECDICT 数据库与词根表是可选扩充，基础词库和词形还原已内置。

```sh
python packaging/run_checks.py
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
node tests/test_domain.mjs
python tests/test_ui.py
python packaging/build_desktop.py
```

PR 自动执行核心、界面与三平台安装检查；新版本合入 main 后自动验证并发布。详见 [RELEASING.md](RELEASING.md)。

| 代码 | 用途 |
|---|---|
| `static/cafe-ui/` | 正式界面与学习流程 |
| `cafe.py` | 页面状态、原子保存、队列与生成接口 |
| `server.py` | 词库、难度段、原有 SRS 与本地服务 |
| `dialogue.py` / `tts_kokoro.py` | 本地写稿、校验、修复与英语配音 |
| `roster.json` / `scenes.json` | 店员、熟客与场景 |
| `packaging/` / `tests/` | 安装包、发布和回归验证 |

</details>

代码采用 [AGPL-3.0](LICENSE)。内置 ECDICT 数据采用 MIT；Kokoro 模型采用 Apache 2.0，分发许可保存在 [resources/licenses](resources/licenses)。用户自行导入的词包不随项目再分发。

<div align="center"><sub>我会一直记得，你喜欢坐的地方的。常来哦。</sub></div>
