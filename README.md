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

目前包含需求、研究综述、项目状态、执行计划、时间轴基础、通用转写入口、环境声事件核心及匿名说话人时间线。stage8 完成续跑产物缓存、事件候选 NDJSON 拆分、模块 RSS 记录及 ENOSPC/缺模型验证路径。Speech、SoundAnalysis 和 FluidAudio 适配器此前已在 macOS 27.2 上构建运行；stage8 本轮 Linux 验证未覆盖 macOS，识别结果尚未人工核验。

本仓库不含原始录音、逐字稿、身份样本、模型权重、运行日志或本机迁移清单。录音和逐字稿可能包含私人内容，因此这些材料保留在本机。

`swift run SoundlogCLI manifest --input <文件或目录> --output-dir <输出根目录>`可生成输入清单。`swift run SoundlogCLI transcribe --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param locale=zh-CN]`用于苹果转写入口。不给`--run-dir`时会在输出根目录创建新的独立运行目录；续跑时传回同一运行目录。Apple Speech适配器已在 macOS 27.2 上构建通过，并对一份长录音完成本机处理；文字质量未经人工核验。Linux会明确报平台不支持并以非零状态退出。

`swift run SoundlogCLI sound-events --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param confidenceThreshold=0.3] [--param minimumEventDurationSeconds=0.5] [--param mergeGapSeconds=0.5]`对每个文件生成 `sound-events.json` 与 `sound-event-windows.ndjson`。摘要保存合并事件、元数据和候选 sidecar 引用；NDJSON 每行保存一个窗口的原始候选，事件索引可用 `SoundEventWindowReader` 回查。阈值范围为 0–1；最短事件时长和合并间隔须为非负秒数，非法参数会报错。真实录音效果与人工误报/漏报抽查仍待验证。

需要一次运行三类分析时，使用 `swift run SoundlogCLI process --input <文件或目录> --output-dir <本机产出目录> [--param locale=zh-CN] [--param confidenceThreshold=0.3] [--param minimumEventDurationSeconds=0.5] [--param mergeGapSeconds=0.5]`。每个录音在同一结果目录内生成 `raw.json`、`transcript.md`（有文字时）、`sound-events.json`、`sound-event-windows.ndjson`、`speaker-timeline.json`、`speaker-aligned-transcript.json/.md`、转写`status.json`及汇总运行状态的`processing-status.json`。三条识别管线独立执行并分别记录状态；逐字稿与说话人关联按区间时间重叠生成候选，不拆分原转写片段、不确定身份。重复指定同一`--run-dir`时，各模块按源/引擎/参数指纹及产物校验续跑；旧版内嵌窗口产物缺少 sidecar 时会重跑一次；processing-status 缓存产物字节数、纳秒 mtime 和 SHA-256，状态文件自身不进入清单哈希。模块状态另记录执行前后 RSS 与进程峰值。

首次在本机安装固定的离线说话人模型时，显式运行 `swift run SoundlogCLI speaker-models install`。此命令从固定版本模型仓库下载、校验权重与署名/来源文件，并加载模型但不处理录音；当前本机回执为 revision `df2625ac79a7ac6b65ad868fee6d80f320da4232`，21 项固定资产共 21,599,417 字节。FluidAudio 0.17.7 要求 macOS 14 或更高版本。SwiftPM 解析该包时还会下载其声明的 Nemo 二进制工件，即使 Swift 6.2 清单关闭了 traits；它与说话人模型分开，保存在忽略的 `.build/` 中。`bash scripts/mac-verify.sh --simulate-missing-model` 使用临时空模型目录进行缺失模型模拟，不删除或更改真实模型缓存；Linux 会在报告中记录 FluidAudio unsupported。

对文件执行匿名说话人分离：`swift run SoundlogCLI speaker-diarize --input <音频文件或目录> --output-dir <本机产出目录>`。每个输入生成 `speaker-timeline.json`，用文件名起始钟表时间映射绝对时间，不添加时区。编号仅在单个文件内有效，不是身份；当前示例运行的准确性尚未人工评价。

Mac 一键合成验证：`bash scripts/mac-verify.sh`。脚本依次运行 `swift build`、`swift test`，生成 1 秒静音 WAV 并调用 `process`，把版本、测试数及各模块状态写到 `/tmp/soundlog-mac-verify.md`；可用 `SOUNDLOG_VERIFY_REPORT=/path/to/report.md` 指定位置。Linux 也可执行，报告按实际结果记录模块状态和退出码。脚本不使用真实录音、不下载模型；Mac 若已安装说话人模型，合成流程会从本机缓存加载它；缺少模型时，状态会记录失败原因。

`process` 会额外生成 `transcript-with-speaker-candidates.md/.txt` 和 `run-manifest.json`。稿件中的说话人标签是匿名时间重叠候选，不代表身份确认；无候选显示“未匹配”。清单记录源哈希、模块状态/指纹、产物哈希、覆盖缺口和首中尾抽样；其中“覆盖”仅指转写覆盖。当前从 WAV、MP3、M4A 容器读取时长：WAV读取data chunk，MP3优先使用Xing/Info或VBRI帧数并按整数样本数扫描回退，M4A读取mvhd/mdhd。损坏或不支持的输入会在清单中保留失败原因并将时长及覆盖报告置空。MP3帧扫描按采样率累计整数样本数，避免长文件的浮点累加漂移。

每次 `process` 批量运行结束均在运行目录下生成 `<运行目录>/记录/整理验收.json`，汇总运行时间、输入路径、是否 mock、文件总数、成功数、失败数、每个文件状态及失败原因。整批有文件失败时 CLI 返回非零退出码，但验收记录与已完成产物照样写出。

Linux 开发或无原生模型环境下，可通过环境变量 `SOUNDLOG_MOCK_ENGINES=1` 或 CLI 参数 `--param engines=mock` 开启 Mock 模式。开启时使用 Mock 假引擎运行转写、声音分类和说话人分离（产物引擎标识包含 `mock`），Mock 引擎会真实读取并校验音频文件容器和时长，损坏或无法读取时如实报错失败。不开 mock 时行为与原生一致（Linux 记录 unsupported，Mac 使用真引擎）。

## Mac 上批量导入测试

在 Mac 实机上批量处理录音文件的完整步骤如下：

### 1. 编译 release 版本

```bash
swift build -c release
```
编译产物位于 `.build/release/SoundlogCLI`。

### 2. 首次安装离线说话人模型（仅需执行一次）

```bash
.build/release/SoundlogCLI speaker-models install
```
该命令会自动从固定模型仓库下载并校验权重文件至本机缓存，后续运行无需联网。

### 3. 处理整个录音文件夹

将需要处理的录音（支持 wav/mp3/m4a 等格式，文件名格式推荐类似 `20261110120000.wav`）放在一个文件夹中（例如 `~/Recordings`），运行：

```bash
.build/release/SoundlogCLI process --input ~/Recordings --output-dir ~/Output
```
程序会按字母顺序逐个处理其中所有音频文件。若遇到损坏、不可读或无法解析时长的坏文件，会记录失败原因并自动继续处理下一个文件，不会中断整批流程。

### 4. 查看结果与验收记录

每次运行会在输出根目录下生成独立的运行目录（如 `~/Output/run-2026-11-10T18-00-00Z-xxxxxxxx/`）：
- **全量验收清单**：查看 `<运行目录>/记录/整理验收.json`，内含文件总数、成功数、失败数、每个文件的路径/状态/失败原因及各模块状态。
- **单个文件结果**：每个文件在 `<运行目录>/<hash前16位>-<文件名>/` 目录下生成：
  - `raw.json`、`transcript.md`（原始转写与时间戳文本）
  - `sound-events.json`、`sound-event-windows.ndjson`（环境声音事件摘要与流式候选明细）
  - `speaker-timeline.json`（匿名说话人时间线）
  - `speaker-aligned-transcript.json/.md/.txt`（候选说话人对齐逐字稿）
  - `run-manifest.json`（运行清单与指标）
- **失败排查**：当处理未完全成功时，先看 `<运行目录>/记录/整理验收.json` 确定哪些文件失败及原因；需要看底层详情时，查看对应文件目录下的 `processing-status.json`（包含各模块的具体错误信息与底层系统错误码）。

## 技术边界

苹果原生转写、声音分类及 FluidAudio 说话人分离均已有本机实跑；识别结果仍未经人工抽查，不承诺识别准确率或处理速度。声音分类候选不等于已确认的地点、活动或现场/外放判断。
