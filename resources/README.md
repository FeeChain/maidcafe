# 窗边的第一杯 · v1

`window-seat.apkg` 是随项目附带的原创入门包。包含 24 个咖啡馆常用词、简短中文释义、一组原创中英例句和逐词 MP3。无需下载外部词库即可体验。

文本源文件是 `window-seat.tsv`，四列依次为词、中文释义、英文例句、中文译文，没有表头。文本由本次项目工作编写，未摘录用户现有的第三方 Anki 包。

音频由本地 Kokoro 合成，逐词使用 `af_sarah`。离线招待对话位于 `static/cafe/window-seat.mp3`，Momo 使用 `jf_alpha`，Haruka 使用 `af_sarah`。这不是原声配音。打包使用 genanki，应用读取包仅使用 Python 标准库。

此包可以随 maidcafe 一起分发。独立分享时请同时保留本说明与项目 LICENSE。现有第三方大包的再分发权限未作核实，本次发布材料不包含它们。

本地下载入口 `/window-seat.apkg`。对外分享可将这个文件放到 GitHub Release 或 Google Drive，并以版本号、词数和文件校验值识别更新。学习记录只留在使用者本机，不包含在词包中。
