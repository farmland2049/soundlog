# soundlog

本地随身录音整理项目。项目目标是根据录音文件名和音频内容生成逐字稿及绝对时间戳、独立识别环境声音候选，并尽可能区分不同人的声音。具体规则见[需求说明](需求说明.md)。

## 项目文档

- [需求说明](需求说明.md)：当前功能范围与时间轴、观测/推断边界。
- [项目状态](PROJECT_STATUS.md)：截至 2026-11-10 的验证进展与未实施事项。
- [后续执行计划](.hermes/plans/2026-11-09_144613-soundlog.md)：六阶段方案；声音事件管线、匿名说话人时间线及 FluidAudio 离线分离适配器已接入。
- [输出格式](资料/输出格式.md)：共同时间轴及首版结果字段约定。
- [技术调研综述](资料/2026-11-09-Mac本地环境音与说话人识别/综合调研.md)：本地候选路线及公开证据限制。

公开仓库：[farmland2049/soundlog](https://github.com/farmland2049/soundlog)。

## 当前状态

目前包含需求、研究综述、项目状态、执行计划、时间轴基础、通用转写入口、环境声事件核心及匿名说话人时间线。Speech、SoundAnalysis 和 FluidAudio 适配器均已在 macOS 27.2 上构建运行；一份长录音已完成三类本机处理，结果尚未人工核验。

本仓库不含原始录音、逐字稿、身份样本、模型权重、运行日志或本机迁移清单。录音和逐字稿可能包含私人内容，因此这些材料保留在本机。

`swift run SoundlogCLI manifest --input <文件或目录> --output-dir <输出根目录>`可生成输入清单。`swift run SoundlogCLI transcribe --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param locale=zh-CN]`用于苹果转写入口。不给`--run-dir`时会在输出根目录创建新的独立运行目录；续跑时传回同一运行目录。Apple Speech适配器已在 macOS 27.2 上构建通过，并对一份长录音完成本机处理；文字质量未经人工核验。Linux会明确报平台不支持并以非零状态退出。

`swift run SoundlogCLI sound-events --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param confidenceThreshold=0.3] [--param minimumEventDurationSeconds=0.5] [--param mergeGapSeconds=0.5]`对每个文件生成 `sound-events.json`，保留分类窗口及候选，并输出按阈值合并的事件。阈值范围为 0–1；最短事件时长和合并间隔须为非负秒数，非法参数会报错。SoundAnalysis 适配器已在 macOS 27.2 上构建通过；真实录音效果与人工误报/漏报抽查仍待验证。

需要一次运行三类分析时，使用 `swift run SoundlogCLI process --input <文件或目录> --output-dir <本机产出目录> [--param locale=zh-CN] [--param confidenceThreshold=0.3] [--param minimumEventDurationSeconds=0.5] [--param mergeGapSeconds=0.5]`。每个录音在同一结果目录内生成 `raw.json`、`transcript.md`（有文字时）、`sound-events.json`、`speaker-timeline.json`、`speaker-aligned-transcript.json/.md`、转写`status.json`及汇总运行状态的`processing-status.json`。三条识别管线独立执行并分别记录状态；逐字稿与说话人关联按区间时间重叠生成候选，不拆分原转写片段、不确定身份。重复指定同一`--run-dir`时，转写按哈希/引擎/参数续跑，声音分类和说话人分离会重新运行。

首次在本机安装固定的离线说话人模型时，显式运行 `swift run SoundlogCLI speaker-models install`。此命令从固定版本模型仓库下载、校验权重与署名/来源文件，并加载模型但不处理录音；当前本机回执为 revision `df2625ac79a7ac6b65ad868fee6d80f320da4232`，21 项固定资产共 21,599,417 字节。FluidAudio 0.17.7 要求 macOS 14 或更高版本。SwiftPM 解析该包时还会下载其声明的 Nemo 二进制工件，即使 Swift 6.2 清单关闭了 traits；它与说话人模型分开，保存在忽略的 `.build/` 中。

对文件执行匿名说话人分离：`swift run SoundlogCLI speaker-diarize --input <音频文件或目录> --output-dir <本机产出目录>`。每个输入生成 `speaker-timeline.json`，用文件名起始钟表时间映射绝对时间，不添加时区。编号仅在单个文件内有效，不是身份；当前示例运行的准确性尚未人工评价。

Mac 一键合成验证：`bash scripts/mac-verify.sh`。脚本依次运行 `swift build`、`swift test`，生成 1 秒静音 WAV 并调用 `process`，把版本、测试数及各模块状态写到 `/tmp/soundlog-mac-verify.md`；可用 `SOUNDLOG_VERIFY_REPORT=/path/to/report.md` 指定位置。Linux 也可执行，报告按实际结果记录模块状态和退出码。脚本不使用真实录音、不下载模型；Mac 若已安装说话人模型，合成流程会从本机缓存加载它；缺少模型时，状态会记录失败原因。

`process` 会额外生成 `transcript-with-speaker-candidates.md/.txt` 和 `run-manifest.json`。稿件中的说话人标签是匿名时间重叠候选，不代表身份确认；无候选显示“未匹配”。清单记录源哈希、模块状态/指纹、产物哈希、覆盖缺口和首中尾抽样；其中“覆盖”仅指转写覆盖。当前从 WAV、MP3、M4A 容器读取时长：WAV读取data chunk，MP3优先使用Xing/Info或VBRI帧数并按整数样本数扫描回退，M4A读取mvhd/mdhd。损坏或不支持的输入会在清单中保留失败原因并将时长及覆盖报告置空。MP3帧扫描按采样率累计整数样本数，避免长文件的浮点累加漂移。

## 技术边界

苹果原生转写、声音分类及 FluidAudio 说话人分离均已有本机实跑；识别结果仍未经人工抽查，不承诺识别准确率或处理速度。声音分类候选不等于已确认的地点、活动或现场/外放判断。
