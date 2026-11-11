# soundlog 第三阶段：AI 记忆体与对标功能落地开发计划

> **制定日期**：2026-11-11  
> **版本**：v1.0 (Phase 3 Master Plan)  
> **执行依据**：基于市面商业标杆（Plaud Note、Limitless）、开源生态（Mem0、OMI、Screenpipe）调研成果，以及与 Basic Memory 知识图谱的技术论证。

---

## 一、项目定位与阶段目标

### 1. 核心使命
构建一套**完全本地离线、隐私安全、硬件无关的音频智能系统**，使日常随身使用的普通录音笔能够直接平替并超越市面商业 AI 专用录音设备（Plaud Note、Limitless Pendant、OMI）的核心智能能力。

### 2. 前序基础成果（已就绪）
* **底座推理速度**：Mac Apple Silicon M 系列芯片下实现 **50x 实时倍速**（25 小时录音约 30 分钟完成）；
* **原生三管线协同**：Apple Speech（逐字稿）+ SoundAnalysis（168+ 类环境声音分类）+ FluidAudio（离线说话人聚类）；
* **跨切片全天连续场景重构**：`scripts/build_daily_scenes.py` 按 90 秒自然停顿将碎片文件缝合为连续实体场景，字数覆盖率达 99.7%~100.0%；
* **批处理与自动归档**：`scripts/process-inbox.sh` 实现“放入待处理 -> 自动识别 -> 自动归档源文件 -> 自动级联更新大模型每日场景库”。

### 3. 第三阶段核心攻坚目标
在已有高质量“每日场景全景剧本”基础上，融合 **Mem0 的“原子事实抽取与动态 CRUD 冲突消解机制”** 与 **Basic Memory 的“本地优先显式 Markdown 知识图谱”**，完成以下四大高阶能力落地：
1. **全天日程与生活工作轨迹复盘（Daily Journal）**；
2. **待办事项、承诺与截止日期自动抽取（Action Items & Commitments）**；
3. **结构化会议纪要与可视化思维导图（MindMap）自动生成**；
4. **声音记忆库全局问答与语义检索（Ask My Memory / Audio RAG）**；
5. **常接触人物声纹确认与社交画像图谱演进（Speaker Persona & Social Dynamics）**。

---

## 二、系统总体架构设计

```mermaid
flowchart TD
    subgraph Layer 1: 底层感知与场景重构 (已完成)
        A["普通录音笔原始音频 (WAV/MP3/M4A)"] --> B["SoundlogCLI 本地原生三引擎"]
        B --> C["每日场景全景库 (Daily Scene Dossiers)"]
        C --> D["时序速览表 + 90s停顿剧本 + 声学环境物理证据"]
    end

    subgraph Layer 2: AI 场景智能提炼引擎 (Epic 1)
        D --> E["LLM 高阶场景提炼器 (Local Ollama / API)"]
        E --> F1["全天日程轨迹复盘 (Daily Journal)"]
        E --> F2["待办承诺清单 (Action Items & Commitments)"]
        E --> F3["结构化脑图与纪要 (Mermaid/Markmap MindMap)"]
    end

    subgraph Layer 3: 记忆流转与冲突消解层 (Epic 2: 借鉴 Mem0)
        E --> G["Mem0-style 记忆仲裁器 (CRUD Resolver)"]
        G -->|检索历史相似记忆| H["对比新旧事实 (ADD / UPDATE / DELETE / NONE)"]
        H --> I["提炼原子 Observations: [decision]/[health]/[todo]"]
        H --> J["构建实体 Relations: [[Person/XX]] / [[Project/XX]]"]
    end

    subgraph Layer 4: 知识持久化与全局问答 (Epic 3 & 4)
        I & J --> K["Basic Memory 本地知识图谱 (Markdown)"]
        K --> L["睡眠反思内化 (memory-reflect 沉淀人物/健康/项目专有笔记)"]
        K & D --> M["多模态问答检索 (Ask My Memory / Audio RAG)"]
        M --> N["用户终端问答交互 (CLI / Web / 聊天助手)"]
    end
```

---

## 三、四大核心模块（Epics）分解与实施计划

### Epic 1: 高阶场景智能生成器（对标 Plaud 模板与脑图）
*目标：直接消费 `每日场景/` 下已清洗好的剧本，产出专业级会议纪要、待办清单与思维导图。*

* **Task 1.1: 全天日程与轨迹复盘生成器 (`scripts/generate_daily_journal.py`)**
  * 结合场景起止时间、Top 3 声学环境（如车内、打字、进餐）与对话内容，输出清晰的时间线流向；
  * 提炼全天情绪状态、社交强度与生活/工作比例；
  * 输出文件：`产出/大模型分析素材/每日场景/YYYY-MM-DD_全天日程复盘.md`。
* **Task 1.2: 结构化会议纪要与可视化思维导图生成器 (`scripts/generate_mindmap.py`)**
  * 针对每个大于 15 分钟的重点实体场景，提炼“讨论背景”、“核心观点与分歧”、“结论与共识”；
  * 自动输出标准 **Mermaid `mindmap`** 语法树及 **Markmap** 结构，支持本地 Markdown 查看器与网页一键秒级渲染。
* **Task 1.3: 待办事项与承诺提醒提取器 (`scripts/extract_action_items.py`)**
  * 定向抓取第一人称承诺（“我答应买...”、“我明天联系...”）与他人交办事项；
  * 输出结构化 Checklist，包含：事项内容、责任人、截止时间线索（Due Date）、上下文原始语境链接；
  * 支持导出为标准 Markdown Todo，可直接被 Apple Reminders、Obsidian 或 Logseq 同步。

---

### Epic 2: Basic Memory 双向联动管道（融合 Mem0 冲突消解机制）
*目标：将音频析出的事实无缝注入本地 Basic Memory 知识图谱，实现持久记忆，杜绝上下文污染。*

* **Task 2.1: 场景到记忆的 Ingest 适配器 (`scripts/soundlog_to_basic_memory.py`)**
  * 遵循 Basic Memory 的 `memory-ingest` 规范；
  * 为每个自然日生成一条 `type: Meeting` 或 `type: DailyLog` 的主笔记；
  * 提取原子化 Observations：
    * `- [decision] 具体决策内容 #标签`
    * `- [health] 身体状况或用药反应 @occurred:YYYY-MM-DD`
    * `- [todo] 待办承诺 @due:YYYY-MM-DD`
    * `- [insight] 个人专业思考或哲学领悟`
* **Task 2.2: 借鉴 Mem0 的动态 CRUD 冲突消解器 (Memory Resolver)**
  * 在向 Basic Memory 写入新 Observation 前，通过 MCP 调用 `search_notes` 检索历史相似事实；
  * 让 LLM 对比新旧事实，执行决策：
    * `ADD`：全新事实，直接追加；
    * `UPDATE`：修正旧事实（如更正了某人的联系方式或项目计划），更新对应笔记行；
    * `DELETE`：废弃旧事实（如明确表示不再执行某项事务）；
    * `NONE`：重复已知事实，直接跳过。
* **Task 2.3: 睡眠反思内化联动 (Sleep-time Reflect Trigger)**
  * 提供一键触发或按日程触发 `memory-reflect` 技能的接口；
  * 引导系统自动将碎片事实折叠沉淀到永久笔记（如：`notes/health/headache-tracker.md`、`notes/people/child.md`）。

---

### Epic 3: 声音记忆库全局问答与语义检索（Ask My Memory / Audio RAG）
*目标：让用户能够用自然语言随时盘问过往所有录音中的任何细节，对标 Limitless "Ask Your Memory"。*

* **Task 3.1: 本地场景向量化与混合索引 (Hybrid Local Index)**
  * 采用本地轻量嵌入模型（如 `bge-small-zh-v1.5` 或 Apple MLX 优化模型）；
  * 基于 SQLite-vec（纯本地嵌入式库，零后台服务依赖）或 Chroma，为 `每日场景` 中的每个场景块建立向量索引；
  * 存储元数据：日期、起止时间戳、说话人列表、主要环境声标签、场景总结。
* **Task 3.2: 统一问答交互入口 (`SoundlogCLI ask "<查询内容>"`)**
  * 实现双引擎混合召回（Hybrid Retrieval）：
    1. **图谱召回**：通过 Basic Memory 查询明确的实体关系（“张三参与了哪些会议？”）；
    2. **语义向量召回**：通过 SQLite-vec 查询模糊语义（“我什么时候提到过轮胎漏气或买海鲜？”）；
  * 融合召回上下文后由本地 LLM / 商业 API 回答，并附带精确到秒的录音时间戳与场景链接。

---

### Epic 4: 说话人实名绑定与社交关系画像（Speaker Persona & Social Dynamics）
*目标：从文件内匿名 S1/S2 聚类，演进为跨天跨文件的真实人物画像系统。*

* **Task 4.1: 本地只读声纹身份库快捷标注工具**
  * 在完全保护隐私的前提下，提供便捷的 CLI / 脚本交互：允许用户听取 5 秒代表片段，确认“S1 = 我本人”、“S2 = 伴侣”、“S3 = 同事老李”；
  * 利用 `SoundlogCore` 已实现的 `IdentityLibrary` 骨架保存声纹特征向量。
* **Task 4.2: 跨文件身份自动传播与社交画像构建**
  * 新录音处理时自动比对确认的声纹，自动将匿名代号替换为实名；
  * 自动统计与各人物的沟通频次、共同讨论的核心议题与互动时间线。

---

## 四、分阶段落地路线图 (Milestones & Schedule)

| 里程碑 | 周期目标 | 交付产物 | 验收标志 |
|---|---|---|---|
| **M1: 场景高阶智能原型验证** | 第 1 周 | `scripts/generate_daily_journal.py`<br>`scripts/generate_mindmap.py`<br>`scripts/extract_action_items.py` | 针对现有的 11-07 和 11-08 录音素材，成功生成首份包含 Mermaid 脑图、待办清单和全天日程复盘的完整报告。 |
| **M2: Basic Memory 自动化入库** | 第 2 周 | `scripts/soundlog_to_basic_memory.py`<br>Mem0-style 冲突判定 Prompt 模块 | 每日录音流水线跑完后，自动向 Basic Memory 知识库中生成结构化 `DailyLog` 笔记，准确提取原子 Observations 与 Relations。 |
| **M3: 睡眠反思与图谱内化** | 第 3 周 | `memory-reflect` 级联脚本与人物/健康专有档案更新 | 自动将 11-08 的用药头痛反应沉淀至个人健康笔记，将 AI 管理学观点沉淀至研究笔记。 |
| **M4: 本地声音记忆问答 (Ask AI)** | 第 4 周 | `SoundlogCLI ask` 命令<br>SQLite-vec 本地场景检索管线 | 在终端输入自然语言问题，1秒内准确检索到历史录音中的对应场景、时间戳并完成精准问答。 |
| **M5: 说话人身份确认与闭环** | 第 5 周 | 交互式声纹确认工具与跨天实名对齐 | 用户标记本人声音后，全天场景自动识别说话人，生成社交互动图谱。 |

---

## 五、核心约束与数据安全红线（不变原则）

1. **绝对本地优先 (100% Local-First)**：
   * 录音源文件、逐字稿、声纹向量、Basic Memory 知识库严格保留在本地磁盘，受 `.gitignore` 保护，绝不上传第三方云端；
2. **人类完全可审计 (Inspectable & Editable)**：
   * 所有的记忆沉淀物均为标准 Markdown 文本，用户可随时通过 Obsidian、VS Code 查看、修改、更正或物理删除，拒绝不可控的数据库黑盒；
3. **保持机器初稿边界**：
   * AI 提取的结论、画像与推断严格标明为“机器推断”，不擅自将其定性为既定事实，保留原始音频绝对时间戳供随时回听复核。
