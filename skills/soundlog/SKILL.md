---
name: soundlog
description: "使用 Soundlog 在本机转写、分类环境声、分离说话人、对齐原文并按天归档；也可查看归档进度或单独查询录音证据。"
---

# soundlog

1. 用本 skill 的 `python3 scripts/locate_project.py` 定位 Soundlog 项目。显式路径无效时停止。
2. 进入项目目录，读取项目入口和 README，再按用户目的操作。
   - **开始／处理录音／继续**：运行 `python3 scripts/soundlog_pipeline.py start`，检查 `complete`、`updatedDates`、`archiveIndex` 及尚待处理文件。文件仍在写入时等待稳定后重试。对本轮待发布日期执行 `prepare-analysis --date YYYY-MM-DD`，阅读返回请求与 `sameDaySources`，按 `scripts/pipeline-agent.md` 接续到交付。
   - **查看进度**：运行 `python3 scripts/soundlog_pipeline.py status`，回报音频归档状态。历史语义任务在 `legacySemantic` 中单独保留。
   - **询问录音内容**：按所问范围读取录音证据。新资料从 Basic Memory 的 `soundlog/sources/YYYY-MM-DD.json` 查日期、证据编号和原音偏移，历史成果从既有交付查看。

音频入口使用本机引擎。处理成功的源音频进入 `录音/已归档/`，机器稿与匿名说话人证据按原时间轴保存。文件内匿名标签按录音限定，保留机器识别的准确性边界。完成时报告实际更新日期、可回查的归档入口及失败或未完成项。
