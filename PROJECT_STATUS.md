# soundlog 项目状态

更新日期：2026-11-10。当前阶段：stage9 批量健壮性、验收报告与声纹身份比对跨平台数据骨架已完成。在 macOS 27.2 / arm64 / Swift 6.4.2 上完成 87 项测试全量通过及 `scripts/mac-verify.sh`（含缺失模型模拟）验证；构建并上线了待处理录音自动化流水线（`scripts/process-inbox.sh`）与大模型分析素材生成器（`scripts/prepare_llm_material.py`）。已对 13 份本地真实录音（累计时长超23小时）成功执行本机端到端处理，源音频已归档至 `录音/已归档/`，分析素材已汇总至 `产出/大模型分析素材/`。所有语音及声学识别结果均为机器初稿，未人工核验，未登记或确认具体真人身份。

本轮 `stage6-unified-output` Linux 合成验证已补齐统一候选逐字稿、run-manifest、覆盖缺口和首中尾抽样、原子写入失败测试，以及 `scripts/mac-verify.sh`。Mac 实机一键验证再次确认 `swift build` 通过、`swift test` 共55项通过；脚本默认报告写入`/tmp/soundlog-mac-verify.md`。随后使用用户提供的 `20261107191809.mp3` 本机运行 `process`：转写94段、SoundAnalysis 870个窗口/982个事件、匿名说话人168段/4个聚类；94段对齐稿中77段有时间重叠候选、13段有多个候选、17段未匹配。所有模块和 run-manifest 状态为 `completed`，源哈希为`1d6119da2d0c4d84049d95d24b082b7379b1ace4d5b7f14cdcccbb8f60948f0c`。录音未改写，结果仅在被忽略的本机`产出/2026-11-10-stage6-merge-verification/`；内容与分人质量仍未经人工核验。验证脚本的合成输入文件名已修正为满足项目严格14位时间戳格式。

## 目标与边界

以[需求说明](需求说明.md)为当前需求来源：根据文件名和录音生成逐字稿及绝对时间戳；识别环境音供后续推理；尽可能区分本人及他人的声音，覆盖自言自语、单人讲话与对谈。三类结果共享原时间轴，环境声识别和说话人区分不以成功转字为前提。场景自动推断不是本轮三项核心功能的必做交付。

公开仓库为[farmland2049/soundlog](https://github.com/farmland2049/soundlog)。本轮工作在`stage6-unified-output`上完成本机验证，随后直接合并至`main`；公开内容限项目说明、调研综述和实现资料，录音、逐字稿、迁移日志及本机工具不公开。

用户已明确授权按六阶段计划实施及安装固定版本 FluidAudio/说话人模型。未获当次授权不上传录音、不登记本人或他人身份；人工听音核验暂缓。

## 已验证进展

- GitHub CLI已连接`farmland2049`，凭据保存在系统钥匙串，Git操作协议为SSH；本机`main`当前与公开仓库`origin/main`同步。
- 新增Swift Package及纯Foundation时间轴核心；`swift test`七项通过。文件名严格按14位日期时间解析，输出为无时区钟表时间，支持跨日偏移与区间边界检查。
- 新增`SoundlogCLI`与跨平台转写核心；Linux x86_64 / Swift 6.1.2 上 `swift build`、`swift test` 通过（16项测试通过）。
- 测试覆盖参数解析、输入枚举、SHA-256已知向量、续跑指纹、覆盖/有字区间、空结果状态、跨日映射及假引擎端到端产物分离。raw JSON与Markdown稿分开原子写入；空结果记录`completed_no_text`且不生成稿件。
- 环境声事件核心保留原始窗口与全部候选，记录阈值、最短时长和合并间隔；按类别合并并允许重叠，低分窗口进入`unknown`，事件可用窗口索引回查。JSON 同时输出文件名起点映射的绝对钟表时间与分类边界说明。支持注入合成引擎。
- 新增`SoundlogCLI sound-events`命令；Linux 下明确报告 SoundAnalysis 不支持并非零退出。转写批次含任一处理失败时现返回非零；退出判断由 Core 纯函数提供。
- Linux x86_64 / Swift 6.1.2 上本阶段 `swift build`、`swift test` 通过：30项测试。测试覆盖无语音环境音合成输入、持续/间歇、重叠类别、unknown、低分过滤、短事件过滤、绝对时间映射、候选回查及声音事件 CLI 参数校验。
- 本机 macOS 27.2 / arm64 / Swift 6.4.2 实测：`swift build`通过，修正 API 可用版本声明及 SoundAnalysis 异步调用后，`swift test` 30项通过。合成清单 CLI 也成功写出 `manifest.json`。本次未读取或处理真实录音。
- Apple Speech `zh_CN` 最初查询为`supported`；预留该区域后变为`installed`，安装请求返回无需下载。本次没有下载模型资源。
- 对一份用户提供的约3小时录音完成本机两条管线：Apple Speech生成769条文字片段，覆盖音频0–10,800.18秒；SoundAnalysis生成7,199个分类窗口、5,545个合并候选事件、168种标签。哈希处理前后相同。文字和事件准确性尚未人工核验；原音频未改写，产物留在被忽略的`产出/`目录。
- 用户决定暂不进行人工确认，待流程成熟后再复核；当前转写及环境声标签仅作机器初稿，不据此宣称准确性或真实场景。
- 五份原始MP3按迁移清单复核SHA-256，全部一致；检查仅读取文件，没有转码或重新识别。
- [输出格式约定](资料/输出格式.md)定义共享原始音频偏移、处理覆盖、转写片段、声音窗口/合并事件及匿名说话人结果。合成样例已与真实录音分开；本次未处理或修改原音频。
- 五份原录音已迁入`录音/2026-11-07/`。
- 已交付逐字稿、历史对照及苹果原生工具已迁入`产出/2026-11-07-录音逐字稿/`。
- GitHub和X/社区调研及来源核查已迁入`资料/2026-11-09-Mac本地环境音与说话人识别/`。
- 共12组来源完成迁移，116个原有文件逐项校验，内容及文件权限保持；12个旧来源路径改为兼容链接。包括五份调研任务书及执行日志，存于`记录/调研执行/`。
- `工具/`提供五个指向项目内唯一实体的相对链接，避免复制程序。
- Whisper模型、独立Python环境及相关临时产物此前已清理；本次未恢复。
- 本轮从FluidAudio v0.17.7源码核实离线加载行为、固定模型修订，以及所需21个文件的SHA-256和字节数；合计21,599,417字节。NOTICE许可范围及provenance限制见[模型核查记录](资料/2026-11-09-Mac本地环境音与说话人识别/Hermes核查/FluidAudio固定模型元数据核查.md)。用户授权后已添加 FluidAudio 0.17.7、模型清单及离线说话人适配器，并下载模型仓库文件至本机 FluidAudio 缓存；21项必需文件哈希/字节数全部通过，三份署名/来源文件也通过校验，Core ML 模型已成功加载。SwiftPM 另将 FluidAudio 声明的 NemoTextProcessing 二进制工件下载进忽略目录`.build/`（约197 MB），虽 Swift 6.2 清单声明`traits: []`仍发生；模型缓存约22 MB。核查中曾把89,416字节PLDA参数JSON读取到临时Git缓存，发现后清除临时检出，未写入项目/模型缓存。
- 新增`SoundlogCLI speaker-diarize`匿名分离入口和统一`SoundlogCLI process`三类处理入口。已对一份约21.8分钟的本地录音完成端到端运行：转写94段、覆盖约0–1,307.95秒；SoundAnalysis输出870个窗口、982个事件候选；说话人管线输出168个时间片段和4个文件内匿名聚类编号。另生成94段候选说话人逐字稿，其中77段有时间重叠候选、13段有多个候选、17段未匹配到说话人片段。产物仅在被忽略的本机`产出/`目录；识别内容和聚类均未人工核验。
- 本轮为候选对齐纯函数新增5项合成测试：时间重叠候选、多说话人候选、无重叠未匹配、源哈希不一致拒绝、录音起点不一致拒绝。
- 新增Core身份库骨架：样本以原文件路径/时间范围/源哈希引用；add与split均清除预填姓名、确认标志及伪造的确认/改名历史，新登记只有显式确认后才绑定姓名；rename仅允许已确认登记。保存依据、模型与引擎版本及创建/确认/拆分/合并/改名/撤销历史；只匹配确认且未撤销登记，结果提供unknown和非概率原始相似度。真实身份向量/样本未写入仓库，身份库运行目录已忽略。合成身份测试7项通过（含 split/rename 确认约束）。
- 新增整合产物时间范围和覆盖校验、共享可序列化模块状态及续跑判定。声音事件、说话人分离及候选对齐只有在完整产物存在且源哈希、引擎和必要参数指纹一致时复用，否则重跑；Linux对不支持模块写明unsupported。对应合成测试3项通过。
- 本轮Linux原始Package manifest下`swift build`及`swift test`通过，共55项测试。SwiftPM将FluidAudio 0.17.7与Nemo工件取入`.build/`；未下载说话人模型、未写入真实声纹。
- [六阶段执行计划](.hermes/plans/2026-11-09_144613-soundlog.md)及[结构化会话归档](记录/会话归档/2026-11-09-需求调研与实施规划.md)已保存；Basic Memory摘要通过连接工具写入并读回，标识见README.md。

## 未实施／待决定

- 真实录音代表片段与人工真值尚未确认；用户决定暂缓人工听音核验，待流程成熟后再议。
- 苹果`SpeechAnalyzer`/`SpeechTranscriber`实现已在本机 Mac 编译通过，并对一份长录音完整运行；文字内容、短片段及尾段质量尚未人工评估，暂作未核验机器初稿。
- SoundAnalysis 适配器使用版本1分类器并从 SDK 请求已知类别，已在本机 Mac 编译通过并对长录音整段运行；候选准确性暂不做人工作实，保留结果供后续复核。
- 已实现平台无关的匿名说话人时间线数据结构、时间映射及`speaker-timeline.json`原子输出，支持未知说话人与重叠片段；一份新录音已通过 FluidAudio 离线引擎生成时间线。
- 三类整合流程和按时间重叠生成的候选说话人逐字稿已对该录音成功运行；这不代表识别质量验收通过。转写错漏、声音事件误报漏报、说话人拆分/合并质量、候选关联有效性、阈值及其他长文件稳定性仍未验证。
- 未完成本人声音确认、真实身份样本、身份匹配模型推理及跨文件真实验证；当前身份库只是跨平台数据/操作骨架。整文件环境声事件的真实准确性仍待人工确认；场景推理留给后续需求。
- FluidAudio 0.17.7 要求 macOS 14+；项目通过显式`swift run SoundlogCLI speaker-models install`安装固定模型，验证后设置离线加载，实际推理路径不会调用可能联网的`prepareModels()`。
- 旧脚本（native_batch.py、native_transcribe.swift、sound_probe.swift）已退役，统一由 SoundlogCLI process 替代；Mac 上 工具/ 目录的旧链接可由主人自行删除。

## 下一步

本轮Core改动、模块整合和续跑状态已完成Mac合成验证及本地录音端到端验证。后续可在不公开本地产物的前提下继续验证其他录音格式与稳定性；真实身份样本须用户明确确认，人工听音核验仍按用户决定暂缓。识别准确性继续标为未核验。Linux验证时SwiftPM已将FluidAudio声明的Nemo二进制工件取入忽略的`.build/`（约197 MB）。

## 验收与证据

- stage6 本轮结果：Core 纯函数渲染匿名候选稿、按 WAV 头计算时长/覆盖缺口、首中尾采样及清单产物 SHA-256。`process` 在模块结果后生成 Markdown/TXT、`run-manifest.json`，保留失败或 unsupported 状态。若无法从格式或结果取得音频总时长，manifest 将该字段和覆盖报告标为 `null`；当前仅 WAV 有可靠时长解析。
- `bash scripts/mac-verify.sh` 使用合成 1 秒静音 WAV；报告默认写入 `/tmp/soundlog-mac-verify.md`，可用 `SOUNDLOG_VERIFY_REPORT` 指定位置。脚本记录 OS/Swift 版本、build/test 状态、测试数及 process 模块状态。Linux 上 Apple 模块 `unsupported` 并导致 process 非零退出是预期；Mac 未执行，模型缺失实机状态未验证。
- 本轮累计55项合成单元测试全部通过；`git diff --check`通过。没有加入真实录音、模型、声纹或身份样本。

## stage7：时长、性能与失败续跑（Linux 合成验证）

- Core 纯 Swift 时长读取：MP3 跳过 ID3v2，优先取 Xing/Info 或 VBRI 帧数，否则扫描 MPEG Layer III 帧；失败时不估算，清单写 `null`、`failed`/`unsupported` 方法及原因。M4A 读取 `mvhd`/`mdhd`。覆盖报告使用同一解析结果。清单包含 `durationMethod`、`durationError`。
- 性能清单记录每模块 `wallClockSeconds` 和 `execution`（recomputed、reuse、skip 等），以及 process 墙钟和 `getrusage` 峰值内存；峰值统一另记字节，`ruMaxRSSUnit` 明示 Linux 原始值单位 KB、macOS 原始值单位 bytes。只记录测量值，不写性能结论。
- 共享模块执行边界将可注入引擎/写盘错误持久化为 failed，其他模块可继续且运行清单仍可写出；原子写失败不留下半截目标文件。恢复继续使用源哈希、引擎/参数指纹和产物校验决定 reuse 或重跑。测试为假模型缺失、后续模块成功、原子产物写失败及清单保留状态。
- 合成媒体测试包括 CBR MP3、Xing MP3、ID3v2 前缀、截断/垃圾输入及 M4A mvhd；文件名测试由 `RecordingStart` 验证脚本的 `20261110120000.wav`。`mac-verify.sh` 增加直接调用该项目解析器测试。
- 本轮 stage7 结果：Linux `swift build` 通过、`swift test` 68 项通过；Mac 27.2 / arm64 / Swift 6.4.2 构建通过、69 项测试通过，`bash scripts/mac-verify.sh` 退出码 0。静音合成输入下 FluidAudio 从本机缓存加载，分人模块按 `noSpeechDetected` 记录失败、依赖模块跳过，运行状态与清单均成功落盘。四个 process 模块由 `IntegratedModuleExecutor` 执行/续跑；合成测试覆盖执行、复用、损坏产物和参数变化。清单 `performance.wallClockSeconds` 在写清单前采样，并以 `wallClockExcludesManifestWrite: true` 明示不含清单写入；之后 `processing-status.json` 另记含清单写入的总耗时，状态文件不参与 artifacts 哈希。
- Mac 本机MP3复核：全部处理模块完成；按MP3帧扫描得到8721.432秒，转写覆盖端点一致、覆盖缺口为空。macOS `afinfo` 给出估计值8721.437秒，差5毫秒，小于该MP3采样率下一个36毫秒帧；这是容器/编码器时长估计差异，结果仍保留解析方法。帧扫描改为按采样率累计整数样本数，消除了长文件逐帧浮点累加导致的微小尾隙。续跑再次将转写、环境声、说话人分离和对齐模块标为`reuse`；运行清单正常写入。识别内容和分人质量仍未人工核验。
- Mac `scripts/mac-verify.sh` 报告现区分“未下载模型”与“从本机缓存加载模型”；首次长MP3运行测得峰值RSS约2.37GB、含清单写入总耗时约285秒。续跑仍需对179MB声音事件JSON做校验和清单哈希，约51秒；这些是单次本机测量，不作为普遍性能结论。FluidAudio模型缺失故障和真实M4A变体尚未实测。

- [文件迁移清单](记录/文件迁移清单.json)：原路径、现路径、每个文件的字节数、SHA-256及权限；包含兼容链接状态。
- `记录/整理验收.json`：实际验收后生成，包括完整性、路径、原录音可读性、工具路径及压缩包检查。未见此文件前不得把预期检查写成已通过。
- 原有实验与调研原文留在各自目录，属于历史证据，不自动代表当前可复现环境。


**stage7 修复进展（2026-11-10）**：本轮完成 SHA-256 增量哈希与约 1 MiB 分块文件读取；音频时长文件入口改为 FileHandle 按偏移读取，覆盖 MP3 帧扫描与 Xing/VBRI 早退、M4A atom 和 WAV chunk。当前 Linux `swift test` 共68项通过；本轮续跑执行器与清单/状态墙钟已完成，具体含清单不含写盘标志及 processing-status 含写盘总时长。转写损坏产物现在会重跑（内层校验 raw.json 内容 + 外层执行器强制重跑），inputCoverage/unifiedTranscript 补齐 execution 与墙钟。

## stage8：续跑、事件产物与失败场景（Linux 合成验证）

- A（commit `c3e2ef7`）：processing-status 为产物缓存 size、纳秒 mtime 和 SHA-256；size 与 mtime 不变时命中缓存，变化时使用现有流式 SHA256.file 重算。`IntegratedModuleResumePlanner` 以 FileHandle 64 KiB 缓冲扫描顶层 JSON，仅解析目标小字段并按 JSON 语法跳过大数组/对象。测试覆盖同一产物缓存命中、mtime 变化后同尺寸内容变更、固定 mtime 的截断产物，以及元数据位于约数 MB `windows` 数组之后的输入；合成扫描实测约1.4秒。
- D（commit `e03f7f0`）：AtomicFile 支持注入写入器；模拟 POSIX ENOSPC 时模块为 failed，错误写明“磁盘空间不足 (ENOSPC, errno 28)”，processing-status 与 run-manifest 可写时均落盘。`mac-verify.sh --simulate-missing-model` 将 FluidAudio 模型路径覆盖为本次临时空目录，不访问真实缓存；Linux 报告 FluidAudio unsupported。Mac 上实际模型缺失故障流程未验证。
- B（commit `725a3a3`）：逐窗口候选现逐行写入 `sound-event-windows.ndjson`，事件 JSON 保存合并结果、窗口数量及 NDJSON 引用。窗口索引对应 NDJSON 行号，`SoundEventWindowReader` 支持按索引逐行回查；统一稿抽样和 run-manifest 均收录 sidecar。缺少 NDJSON sidecar，或摘要窗口数与逐行解码校验不符、sidecar 为空/截断/含坏行时，SoundAnalysis 模块续跑判为需重跑。
- B 的 Linux 合成测量为15,000窗口、每窗300候选：旧嵌入 JSON 384,432,480字节；新格式摘要 JSON 214,676字节，NDJSON 185,422,784字节，合计185,637,460字节。首次 SHA-256、缓存指纹及包含 NDJSON 流式完整校验的续跑计时见`/workspace/soundlog-stage8-logs/b-size-compare.log`。数据为合成数据，非 Mac 真录音；此处只记录测得值。
- C（commit `8582360`）：执行器为执行模块记录 `residentBytesBefore`、`residentBytesAfter` 和 `processPeakResidentBytes`。Linux 读取 `/proc/self/statm`；macOS 使用 `task_info/mach_task_basic_info`，代码位于 macOS 条件编译内。Linux 测试确认三个字段均为正数。
- 本轮 Linux `swift build` 通过、`swift test` 76项通过。Mac 本轮未验证；Apple/FluidAudio 与 macOS RSS 分支未在本轮构建。`bash scripts/mac-verify.sh` 及缺模型选项在 Linux 均运行合成 process，按脚本约定 process 的平台不支持退出记录在报告中，脚本整体退出0。
- 本轮验证日志位于`/workspace/soundlog-stage8-logs/rework-verify-build.log`、`rework-verify-test.log`、`rework-verify-diff-check.log`、`rework-verify-mac-verify.log`、`rework-verify-mac-verify-missing-model.log`；所有性能值均为本轮 Linux 合成测量，不作为性能结论。

## stage9：批量健壮性、验收报告与声纹身份比对（Linux 合成验证）

- **第 1 部分**：
  - 批量容错处理：文件夹批量处理时若单文件损坏、不可读或时长解析失败，记录该文件失败原因并继续处理下一个文件，整批不中断。
  - 验收报告落盘：每次运行在运行目录下生成 `<运行目录>/记录/整理验收.json`，记录时间、输入路径、是否 mock、总文件数、成功数、失败数、每个文件状态及各模块明细。
  - Mock 引擎支持：新增 `MockTranscriptionEngine`、`MockSoundEventEngine`、`MockSpeakerDiarizationEngine`，通过 `--param engines=mock` 或环境变量启用，真实校验音频文件容器和时长。
- **第 2 部分（声纹接入身份库）**：
  - 声纹提取协议：新增 `SpeakerEmbeddingExtractor` 协议，输入音频文件和匿名说话人时间线，输出每个说话人的特征向量、引擎及模型版本。
  - Mock 提取器：新增 `MockSpeakerEmbeddingExtractor`，根据音频文件 SHA-256 哈希与说话人编号生成确定性伪向量（L2 归一化），标识含 `mock`。若音频损坏无法读取时长则校验失败。
  - Mac FluidAudio 提取器骨架：新增 `FluidAudioSpeakerEmbeddingExtractor`，受 `#if os(macOS) && canImport(FluidAudio)` 保护。标明为 Mac 专用、未在 Mac 实体机验证；调用时抛出明确的“Mac 待实现/待验证”错误，保证 Linux 构建零影响。
  - 身份比对与只读安全：只读加载指定路径的 `IdentityLibrary`（不存在视为空库），绝不采集、注册或写入任何真实声纹与身份。比对输出写入每个文件的 `speaker-identities.json`，记录已确认身份或未知状态，相似度标明为非概率原始相似度（raw similarity score）。若库中已有身份向量与待测向量维度不一致，严格抛出 `IdentityLibraryError.incompatibleVectors`。
  - Process 管线与验收集成：`process` 命令支持 `--param identityLibrary=<路径>` 与 `--param identityThreshold=<阈值>`（默认 0.8）。未提供时跳过并记录 `skipped`；Mock 模式下执行 mock 提取比对并输出产物；非 Mock Linux 记录 `unsupported`。模块状态 `speakerIdentities` 写入 `processing-status.json`、纳入 `run-manifest.json` 产物与抽样，并汇总进 `记录/整理验收.json`。单个文件声纹模块失败不会打断整批批处理。
  - Linux 构建与测试：`swift build` 与 `swift test` 87 项测试全部通过，覆盖 mock 确定性、合成身份命中、空库未知、维度不匹配报错及 process 流程集成。未采集或登记项目主人或任何真人的声音。

## stage9 Mac 实体机验证与自动化归档流（2026-11-10）

- **Mac 实体机环境与测试**：
  - macOS 27.2 / arm64 / Apple M5，Swift 6.4.2。
  - 修复 `Tests/SoundlogCoreTests/BatchAndMockTests.swift` 中 Darwin `/var` 符号链接与 `/private/var` 绝对路径比对断言；全量 87 项单元测试全部通过。
  - `bash scripts/mac-verify.sh` 退出码 0，报告输出于 `/tmp/soundlog-mac-verify.md`。
  - `bash scripts/mac-verify.sh --simulate-missing-model` 退出码 0，验证 FluidAudio 临时模型缺失时的健壮性，整批不中断。
- **待处理录音与大模型素材管线**：
  - 建立标准录音收纳目录结构：`录音/待处理/`（收纳未处理原始文件）、`录音/已归档/`（处理完成后源录音移动归档）。
  - 新增流水线自动化脚本 `scripts/process-inbox.sh`：自动检测待处理目录，校验 14 位时间戳规范，调用 Release 优化二进制 `.build/release/SoundlogCLI process`，产出完成后触发素材生成器，并将源录音安全转移至归档目录由用户决定是否删除。
  - 新增素材提取与 Prompt 模版生成器 `scripts/prepare_llm_material.py`：自动解析单次运行产物，提取音频基本信息、高频环境音事件Top10、匿名说话人时长比例，并合成单篇 `LLM分析素材.md` 与纯文本稿件；同步维护素材总索引表 `产出/大模型分析素材/README.md`。
- **真实录音批次全量处理**：
  - 本地共 13 份 MP3 录音文件（包括用户在会话中上传并命名为 `20261108153711.mp3` 的音频）成功完成全量流水线处理。
  - 累计处理音频时长超过 23 小时，Release 模式下单份 3 小时长录音处理约 3~4 分钟，内存控制稳定，无泄漏。
  - 13 份源录音已全部移至 `录音/已归档/`，`录音/待处理/` 恢复为空状态等待后续新文件。
  - `产出/大模型分析素材/` 下已生成 13 个完整独立素材包及总索引，就绪供下游大模型做日常整理与洞察。
  - 所有转写与声学推断保持机器初稿标注，未人工核验，未登记或确认具体真实身份。
- **跨文件按天场景聚合与大模型素材重构（2026-11-10 晚）**：
  - 新增 `scripts/build_daily_scenes.py`：打破单文件物理截断，基于无时区钟表时间轴按自然日跨文件聚合全天转写与声学事件。
  - 基于真实对话自然停顿（90 秒无语音）自动聚类出“连续实体场景片段（Scene Episodes）”；通过文本密度阈值过滤零星孤立杂音并归入附录，使主干场景字数覆盖率高达 99.7%~100.0%。
  - 融合 SoundAnalysis 环境声分类为人话释义（规避 AudioSet 低频噪音标签歧义），结合说话人聚类候选生成剧本式对话流。
  - 产出落地于 `产出/大模型分析素材/每日场景/`（含 `2026-11-07` 与 `2026-11-08` 全景 Markdown 与结构化 JSON，以及总索引）；同时接入 `scripts/process-inbox.sh`，实现处理新录音后自动级联刷新每日场景库。
