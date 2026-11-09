# soundlog

本地随身录音整理项目。项目目标是根据录音文件名和音频内容生成逐字稿及绝对时间戳、独立识别环境声音候选，并尽可能区分不同人的声音。具体规则见[需求说明](需求说明.md)。

## 项目文档

- [需求说明](需求说明.md)：当前功能范围与时间轴、观测/推断边界。
- [项目状态](PROJECT_STATUS.md)：截至 2026-11-09 的验证进展与未实施事项。
- [后续执行计划](.hermes/plans/2026-11-09_144613-soundlog.md)：六阶段方案；第一阶段时间轴基础已启动。
- [输出格式](资料/输出格式.md)：共同时间轴及首版结果字段约定。
- [技术调研综述](资料/2026-11-09-Mac本地环境音与说话人识别/综合调研.md)：本地候选路线及公开证据限制。

公开仓库：[farmland2049/soundlog](https://github.com/farmland2049/soundlog)。

## 当前状态

目前包含需求、研究综述、项目状态、执行计划、时间轴基础、通用转写入口及环境声事件跨平台核心。SoundAnalysis 和真实录音效果待 Mac 验证。现有历史工具和识别产物不属于本公开版本，也不代表可直接复现。

本仓库不含原始录音、逐字稿、身份样本、模型权重、运行日志或本机迁移清单。录音和逐字稿可能包含私人内容，因此这些材料保留在本机。

`swift run SoundlogCLI manifest --input <文件或目录> --output-dir <输出根目录>`可生成输入清单。`swift run SoundlogCLI transcribe --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param locale=zh-CN]`用于苹果转写入口。不给`--run-dir`时会在输出根目录创建新的独立运行目录；续跑时传回同一运行目录。Apple Speech实现尚未在Mac编译验证，Linux会明确报平台不支持并以非零状态退出。

`swift run SoundlogCLI sound-events --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param confidenceThreshold=0.3] [--param minimumEventDurationSeconds=0.5] [--param mergeGapSeconds=0.5]`对每个文件生成 `sound-events.json`，保留分类窗口及候选，并输出按阈值合并的事件。阈值范围为 0–1；最短事件时长和合并间隔须为非负秒数，非法参数会报错。Linux 可构建和测试核心，但没有 SoundAnalysis，运行该子命令会明确报错并非零退出。SoundAnalysis SDK 实现及真实录音效果**待 Mac 验证**。

## 技术边界

苹果原生转写及声音分类短样本有历史本机实测。FluidAudio 离线说话人方案尚未安装或在本机验证。未经长录音和人工抽查，不承诺识别准确率或处理速度。声音分类候选不等于已确认的地点、活动或现场/外放判断。
