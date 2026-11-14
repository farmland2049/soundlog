# soundlog: 本地随身录音 AI 智能分析与记忆系统

> **核心使命**：构建一套**完全本地离线、隐私安全、硬件无关的音频智能系统**，让日常使用的**普通录音笔**（或任意录音设备）直接拥有并超越当前市面热门 AI 录音/记录/记忆设备（如 Plaud Note、Limitless Pendant、OMI）的核心智能能力。

---

## 为什么做 soundlog？

市面上现有的 AI 录音设备（如 Plaud Note/NotePin、Limitless 等）展示了强大的场景：将日常交谈与会议自动转化为日程、总结、思维导图与个人记忆。然而，它们普遍存在无法忽视的局限：
1. **严重的隐私与保密风险**：全天私密对话、商务会议、医疗健康或家庭生活录音被强制上传至第三方商业云端；
2. **昂贵的专用硬件绑定与订阅税**：硬件售价高昂，且每月需支付高额的云端转写/LLM 订阅费用；
3. **断网与续航受限**：受制于手机蓝牙流式传输或轻薄硬件的电池容量。

**soundlog 的破局方案**：
* **硬件无关 (Hardware-Agnostic)**：您可以使用手头已有的任何普通录音笔（如索尼、飞利浦或平价 USB 录音笔）。它们拥有长达数十小时的强劲续航、物理独立开关与充裕存储。
* **100% 本地优先与数据主权 (Local-First & Zero-Cloud)**：在 Apple Silicon（Mac M 系列）上完全离线推理，音频与文字绝不离开本地。实测吞吐达 **50x 实时倍速**（25 小时录音仅需约 30 分钟）。
* **多模态场景感应 (Multimodal Acoustics)**：不仅做语音转字，更原生融合 **168+ 类环境声音分类**（行车、打字、进餐、欢笑等），为大模型还原真实的物理情境证据。
* **跨切片全天连续场景重构**：彻底打破录音笔每 3 小时一段的生硬硬件物理截断，基于自然交谈停顿（90 秒无语音）自动将全天录音缝合为高密度的**连续生活/工作实体场景剧本**。

---

## 项目路线图 (Roadmap)

- [x] **第一阶段：本地离线分析底座与连续场景构建（已完成）**
  - [x] 纯 Foundation 无时区严格时间戳映射核心；
  - [x] 苹果原生 SpeechAnalyzer 中文转写管线；
  - [x] SoundAnalysis 168+ 类环境声事件分类与流式候选；
  - [x] FluidAudio 0.17.7 离线说话人聚类与区间候选对齐；
  - [x] 自动化收纳与归档流水线（`scripts/process-inbox.sh`）；
  - [x] 跨文件每日场景全景提炼器（`scripts/build_daily_scenes.py`，字数覆盖率 99.7%+）；
  - [x] 87 项跨平台单元测试与 Mac 实体机验证。
- [ ] **第二阶段：市面 AI 录音/记忆设备对标调研与功能规划（进行中）**
  - [x] 调研 Plaud Note、Limitless、OMI、Screenpipe 等硬件与开源生态架构；
  - [x] 梳理高阶功能需求（生活日志、待办提取、思维导图、记忆库 RAG、画像推断）；
  - [ ] 制定普通录音素材对接本地/外部大模型的落地实现方案。
- [ ] **第三阶段：高阶 AI 智能与记忆体落地（规划中）**
  - [ ] 全天活动轨迹与日程自动复盘（Daily Journal）；
  - [ ] 会议纪要、待办事项（Action Items）与承诺提醒自动提取；
  - [ ] 个人记忆库问答与语义检索（Ask My Memory / Audio RAG）；
  - [ ] 个人与常接触人物的声纹绑定与画像演进。

---

## 项目文档

- [需求说明](需求说明.md)：当前功能范围与时间轴、观测/推断边界。
- [项目状态](PROJECT_STATUS.md)：当前验证进展与阶段成果。
- [当前产品目标与迭代开发测试计划](资料/产品目标与迭代开发测试计划.md)：总体功能、下一版范围、测试门槛和后续顺序。
- [内容价值标准](资料/2026-11-13-产品功能与内容价值标准.md)：按目标功能判断高价值内容，独立记录可信度与归属。
- [生成前语义验收流程](资料/语义验收流程.md)：冻结24例金标准与8例留出集，按信息点、引文支持和严重错误评分。
- [历史第三阶段功能开发计划（2026-11-11）](资料/2026-11-11-市面AI录音设备功能与GitHub开源项目调研/后续功能开发计划.md)：对标 Plaud/Limitless 与融合 Mem0 + Basic Memory 的全景落地规划。
- [AI录音设备与开源生态调研报告](资料/2026-11-11-市面AI录音设备功能与GitHub开源项目调研/市面AI录音设备与开源生态调研报告.md)：市面标杆（Plaud/Limitless）与 GitHub 开源生态深度分析。
- [每日场景大模型素材库](产出/大模型分析素材/每日场景/README.md)：已生成的每日高密度场景剧本及 JSON 索引。
- [本地草稿试验与进度边界](资料/本地功能草稿试验.md)：已有模型的离线试验结果、未通过质量项及真实进度查询。
- [四类功能提炼](资料/四类功能提炼.md)：日记、纪要、待办和学习笔记的材料导出、证据校验、局部试验及结果阅读。
- [新版素材与原文检索](资料/场景素材与原文检索.md)：独立快照、完整逐句来源、关键词回查及故障状态。
- [输出格式](资料/输出格式.md)：共同时间轴及首版结果字段约定。
- [技术调研综述](资料/2026-11-09-Mac本地环境音与说话人识别/综合调研.md)：本地候选路线及公开证据限制。

公开仓库：[farmland2049/soundlog](https://github.com/farmland2049/soundlog)。

---

## 快速使用

### 1. 日常随身录音一键处理流水线（推荐）

平时只需将录音笔内的录音文件拷贝至 `录音/待处理/`（文件名格式如 `20261108153711.mp3`），然后执行：

```bash
bash scripts/process-inbox.sh
```

脚本将自动：
1. 校验时间戳并逐个调用 Release 模式原生核心进行三类分析；
2. 提取大模型专属素材并移动源音频至 `录音/已归档/`；
3. **全自动级联重构当天的全天场景剧本**，新版产出位于 `产出/大模型分析素材/每日场景-v2/`，`latest.json` 指向完整快照；旧版素材保留。

---

### 全部录音原文检索（新版）

```bash
python3 scripts/build_daily_scenes.py
python3 scripts/search_recordings.py 轮胎 --date 2026-11-07
```

生成器复用现有运行产物，保留所有长短发言和声学候选；原文检索覆盖未提炼为记忆的内容。新版按文件限定匿名标签，片段、声学候选与现实活动分开。详见[新版素材与原文检索](资料/场景素材与原文检索.md)。

### 2. 底层 CLI 命令说明

`swift run SoundlogCLI manifest --input <文件或目录> --output-dir <输出根目录>`可生成输入清单。`swift run SoundlogCLI transcribe --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param locale=zh-CN]`用于苹果转写入口。不给`--run-dir`时会在输出根目录创建新的独立运行目录；续跑时传回同一运行目录。Apple Speech适配器已在 macOS 27.2 上构建通过，并对一份长录音完成本机处理；文字质量未经人工核验。Linux会明确报平台不支持并以非零状态退出。

`swift run SoundlogCLI sound-events --input <文件或目录> --output-dir <输出根目录> [--run-dir <已有运行目录>] [--param confidenceThreshold=0.3] [--param minimumEventDurationSeconds=0.5] [--param mergeGapSeconds=0.5]`对每个文件生成 `sound-events.json` 与 `sound-event-windows.ndjson`。摘要保存合并事件、元数据和候选 sidecar 引用；NDJSON 每行保存一个窗口的原始候选，事件索引可用 `SoundEventWindowReader` 回查。阈值范围为 0–1；最短事件时长和合并间隔须为非负秒数，非法参数会报错。真实录音效果与人工误报/漏报抽查仍待验证。

需要一次运行三类分析时，使用 `swift run SoundlogCLI process --input <文件或目录> --output-dir <本机产出目录> [--param locale=zh-CN] [--param confidenceThreshold=0.3] [--param minimumEventDurationSeconds=0.5] [--param mergeGapSeconds=0.5] [--param identityLibrary=<身份库路径>] [--param identityThreshold=0.8]`。每个录音在同一结果目录内生成 `raw.json`、`transcript.md`（有文字时）、`sound-events.json`、`sound-event-windows.ndjson`、`speaker-timeline.json`、`speaker-aligned-transcript.json/.md`、转写`status.json`及汇总运行状态的`processing-status.json`；若传入 `--param identityLibrary`，还会进一步提取匿名说话人声纹特征并比对只读身份库，在对应目录写出 `speaker-identities.json`。三条识别管线独立执行并分别记录状态；逐字稿与说话人关联按区间时间重叠生成候选，不拆分原转写片段。重复指定同一`--run-dir`时，各模块按源/引擎/参数指纹及产物校验续跑；旧版内嵌窗口产物缺少 sidecar 时会重跑一次；processing-status 缓存产物字节数、纳秒 mtime 和 SHA-256，状态文件自身不进入清单哈希。模块状态另记录执行前后 RSS 与进程峰值。

若未提供 `--param identityLibrary`，`speakerIdentities` 模块将被跳过并在 `processing-status.json` 中记为 `skipped`。传入身份库时：
- 只读加载身份库文件，若文件不存在则视为空库；流程绝不自动登记、采集或写入任何新身份或真实声纹。
- 比对结果以原始相似度（raw similarity score，非概率）记录已确认身份或未知状态。
- **Mock 模式**：使用 `MockSpeakerEmbeddingExtractor` 根据文件哈希与说话人编号生成确定性伪向量（标识含 `mock`），在 Linux 上可完整跑通流程。
- **Mac 原生实现与待验证事项**：Mac 上使用 `FluidAudioSpeakerEmbeddingExtractor`（受 `#if os(macOS) && canImport(FluidAudio)` 保护）；本适配器为 **Mac 专用，目前未在 Mac 实体机验证真实模型推理 API**，代码中保留骨架并在调用时抛出明确的“Mac 待实现/待验证”错误，真实模型对接留待后续 Mac 环境调试。非 Mock 模式下的 Linux 运行环境如实记录 `unsupported`。单个模块失败不会导致整批批处理中断。

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

## 本地记忆处理（首版）

新增独立本地记忆库，支持逐句证据整理、Markdown 原子记忆、关键词检索、候选确认、更正审核和撤销。采用 Basic Memory 风格的可读笔记与关系，借鉴 Mem0 的增量更新方法；外部模型支持 API 与材料导出／结果导入两种通道，本地模型仅预留接口。

```bash
python3 scripts/memory.py prepare --date 2026-11-07
python3 scripts/memory.py export --date 2026-11-07
python3 scripts/memory.py search 关键词
```

默认 `记忆库/` 已被 Git 忽略；不接入现有正式知识库，不自动运行外部 API。详细协议、配置、审核及验证见 [本地记忆处理](资料/本地记忆处理.md)。

## 技术边界

苹果原生转写、声音分类及 FluidAudio 说话人分离均已有本机实跑；识别结果仍未经人工抽查，不承诺识别准确率或处理速度。声音分类候选不等于已确认的地点、活动或现场/外放判断。
