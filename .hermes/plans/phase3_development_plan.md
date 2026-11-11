# soundlog 第三阶段：AI 记忆体与对标功能落地开发计划 (交互式全景视图)

> **制定日期**：2026-11-11  
> **版本**：v1.0 (Phase 3 Master Plan)  
> **项目根目录文件**：[`/.hermes/plans/2026-11-11_soundlog-phase3-ai-memory-plan.md`](file:///Users/qqiang/AI%20project/06-开发项目/soundlog/.hermes/plans/2026-11-11_soundlog-phase3-ai-memory-plan.md)

---

## 一、战略愿景与底座回顾

### 1. 核心定位
构建一套**完全本地离线、隐私安全、硬件无关的音频智能系统**，使日常随身使用的**普通录音笔**（或任意录音设备）能够直接平替并超越市面商业 AI 专用录音设备（Plaud Note、Limitless Pendant、OMI）的核心智能能力。

### 2. 前序已就绪底座
* **极致性能**：Mac Apple Silicon M 芯片下实现 **50x 实时倍速**（25 小时录音约 30 分钟完成）；
* **多模态感知**：Apple Speech（逐字稿）+ SoundAnalysis（168+ 类环境声事件）+ FluidAudio（离线说话人聚类）；
* **跨切片全天场景重构**：`scripts/build_daily_scenes.py` 按 90 秒自然停顿将碎片文件缝合为连续实体场景（字数覆盖率 99.7%+）；
* **收纳归档闭环**：`scripts/process-inbox.sh` 实现了“放入待处理 -> 自动识别 -> 自动归档源文件 -> 自动级联更新大模型每日场景库”。

---

## 二、系统总体架构：Mem0 + Basic Memory 双核驱动

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
        M --> N["用户终端问答交互 (CLI / 聊天助手)"]
    end
```

---

## 三、四大核心模块（Epics）分解

### Epic 1: 高阶场景智能生成器（对标 Plaud 模板与脑图）
* **Task 1.1: 全天日程与轨迹复盘生成器 (`generate_daily_journal.py`)**：结合场景起止时间、声学背景与对话，提炼全天时间线、情绪与生活工作比例。
* **Task 1.2: 结构化会议纪要与可视化思维导图 (`generate_mindmap.py`)**：针对重要场景输出背景、分歧、共识与决策，自动生成标准 **Mermaid `mindmap`** 代码，支持一键可视化渲染。
* **Task 1.3: 待办事项与承诺提醒提取器 (`extract_action_items.py`)**：定向抓取第一人称承诺（“我答应买...”、“我周五交付...”）与他人交办事项，生成带上下文链接的 Todo 待办列表。

### Epic 2: Basic Memory 双向联动管道（融合 Mem0 冲突消解机制）
* **Task 2.1: 场景到记忆的 Ingest 适配器 (`soundlog_to_basic_memory.py`)**：按自然日生成 `type: DailyLog` 笔记，提取原子化 Observations（`[decision]`、`[health]`、`[todo]`、`[insight]`）与显式双向链接（`[[Person/XX]]`、`[[Project/XX]]`）。
* **Task 2.2: 借鉴 Mem0 的动态 CRUD 冲突消解器 (Memory Resolver)**：写入前先检索历史相似记忆，由 LLM 仲裁执行 `ADD`（增量）、`UPDATE`（覆盖旧认知）、`DELETE`（废除过时信息）或 `NONE`（去重）。
* **Task 2.3: 睡眠反思内化联动 (Sleep-time Reflect)**：一键触发 `memory-reflect` 流程，将日常碎片自动合并沉淀至永久人物档案、健康档案与项目专有笔记。

### Epic 3: 声音记忆库全局问答与语义检索（Ask My Memory / Audio RAG）
* **Task 3.1: 本地场景向量化与混合索引 (Hybrid Local Index)**：采用轻量本地 Embedding 模型结合 SQLite-vec，为每日场景建立轻量级本地向量库。
* **Task 3.2: 统一问答交互入口 (`SoundlogCLI ask "<查询内容>"`)**：结合 Basic Memory 图谱拓扑与向量语义，实现“我什么时候答应过买某样东西”、“关于项目立项我们讨论了什么”等跨天精准溯源问答。

### Epic 4: 说话人实名绑定与社交关系画像（Speaker Persona & Social Dynamics）
* **Task 4.1: 本地只读声纹身份库交互式确认**：在保护隐私前提下，提供便捷终端交互，听取 5 秒音频确认“S1 = 我本人”、“S2 = 伴侣”。
* **Task 4.2: 跨文件身份自动对齐与社交画像演进**：后续新录音自动对齐实名标签，统计互动频次与关注话题。

---

## 四、分阶段落地路线图 (Milestones & Schedule)

| 里程碑 | 交付产物 | 验收标志 |
|---|---|---|
| **M1: 场景高阶智能原型验证** | `generate_daily_journal.py`<br>`generate_mindmap.py`<br>`extract_action_items.py` | 针对现有的 11-07 和 11-08 录音素材，成功生成首份包含 Mermaid 脑图、待办清单和全天日程复盘的完整报告。 |
| **M2: Basic Memory 自动化入库** | `soundlog_to_basic_memory.py`<br>Mem0-style 冲突判定 Prompt 模块 | 每日录音流水线跑完后，自动向 Basic Memory 知识库中生成结构化 `DailyLog` 笔记，准确提取原子 Observations 与 Relations。 |
| **M3: 睡眠反思与图谱内化** | `memory-reflect` 级联脚本与人物/健康专有档案更新 | 自动将 11-08 的用药头痛反应沉淀至个人健康笔记，将 AI 管理学观点沉淀至研究笔记。 |
| **M4: 本地声音记忆问答 (Ask AI)** | `SoundlogCLI ask` 命令<br>SQLite-vec 本地场景检索管线 | 在终端输入自然语言问题，1秒内准确检索到历史录音中的对应场景、时间戳并完成精准问答。 |
| **M5: 说话人身份确认与闭环** | 交互式声纹确认工具与跨天实名对齐 | 用户标记本人声音后，全天场景自动识别说话人，生成社交互动图谱。 |

---

## 五、核心约束与数据安全红线（不变原则）

1. **绝对本地优先 (100% Local-First)**：录音、逐字稿、声纹向量、知识库严格存放在本地磁盘，受 `.gitignore` 保护，绝不上传第三方云端；
2. **人类完全可审计 (Inspectable & Editable)**：所有沉淀均为标准 Markdown，随时可通过 Obsidian / VS Code 查验、修改或物理删除；
3. **保持机器初稿边界**：AI 推断与原始事实严格区分标注，保留原音频绝对时间戳供回听溯源。
