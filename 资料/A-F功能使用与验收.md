# A—F 功能使用与验收

2026-11-16。本版使用现有本机音频引擎和当前agent的语义能力。音频处理可离线；语义工作依赖agent会话，不能称全链断网自治。录音与交付文件留本机，不安装新模型。下列产物含私人资料，`产出/`与`记忆库/`保持Git忽略。

## 使用入口

在项目根运行：

```bash
python3 scripts/soundlog_pipeline.py tick
python3 scripts/soundlog_hub.py --reuse-session
```

第二条命令打印本机工作台地址，Ctrl+C停止。首次运行可省略`--reuse-session`；该选项复用既有本机端口和访问路径，便于重启后继续打开收藏。工作台提供每日首页、全部日期检索、事项跟踪、知识/脑图/信息卡、规整稿与写作素材、证据问答。静态阅读入口是`产出/自动交付/README.md`，无需运行网页服务；问答提交需要网页服务，真正回答由本线程agent执行。

将14位开始时间命名的音频放入`录音/待处理/`，文件稳定60秒后可处理。既有每日8:00（上海时间）自动化会唤醒本线程，读取`scripts/pipeline-agent.md`续做。电脑与应用需可运行，频率并非实时监听。新批次阶段为：

```text
音频处理 → awaiting_agent → ingest → awaiting_screening
         → publish → awaiting_enrichment → finish → idle
```

`publish`只完成基础日交付；必须继续`finish`生成经审阅的事项和派生产物。长材料逐批保存，不预标未读。失败保留日志与中间文件；无新内容不造空日记。整天无转写仍保留明确覆盖缺口及声学证据，不捏造活动。`--adopt`仅显式采用已经处理的历史基线。

## 功能、产物与验证范围

|阶段|可用功能与产物|本版实际验证|
|---|---|---|
|A|日期首页、`timeline.md/json`、`daily-review.md/json`、五类记录、`scenes.json`及结构化场景MD|八天首页与复盘；工作、生活、儿童、成人四种场景实例；跨午夜、全暂缓、外放边界及无文字测试；两份真实旧音频隔离重处理到最终产物|
|B|`task-graph.json`、`task-tracking.md`、不可变图版本、追加历史；支持相同/可能相同/冲突/无关/撤回|208个事项提及，207项；两条经审阅关联。合成测试覆盖冲突、撤回、重试和有依据的相对日期解析|
|C|网页持久化问题队列，原文与保留内容双通道检索，补查、带证据回答、失败/等待/处理中状态，Markdown/JSON导出|页面实际提交并读回回答；六例事后回归包含跨天、否定、无答案、来源归属与不可强合并；逐字引文均通过验证|
|D|儿童/成人独立知识卡MD/JSON，主题关联，Mermaid、可点击SVG脑图、HTML信息卡，明确标记agent新增联想|六个真实主题、两条主题关系；浏览器看到脑图与信息卡，卡片及节点回链原文|
|E|独立规整稿、原句和差异、MARK邻接语境、意图草稿、报告/文章/发言提纲|三份规整对照、两条MARK判断、一份意图草稿、三份写作素材；否定/条件/数字和媒体口令拒绝测试|
|F|六工具只读MCP、受批准的记忆差异/应用/读回/恢复/撤回、fact范围身份确认和解绑、日历草稿/真实执行/幂等/撤销|两个实际MCP客户端会话一致；隔离Basic Memory三种操作MCP读回；用户指定日历真实创建、重试仅一条、撤销后零条|

代码测试与文件哈希只能证明其覆盖的确定性行为。语义由同一agent审阅，独立验收按用户决定留待以后；不提供独立准确率。八天592保留/422暂缓来自1014条候选摘要级初筛，不能称所有摘要细节已经逐句或听音验收。知识和场景有实际实例，六主题并非所有保留内容都已扩展为知识卡。真实全链验证重用了既有录音的新隔离批次；尚没有未见新录音的前瞻验收。

## 事项与时间

每条事项同时显示原话性质、期限原话、录音时间和当前状态。录音中说已完成仅代表当时陈述，当前状态仍未知；缺少新录音不等于尚未完成。只有`same_task`会合并，`possible_same_task`保持并列，冲突保存双方依据。关联撤回追加新记录，不删历史。

```bash
python3 scripts/soundlog_features.py tasks --links 经审阅的关联.json
```

关联文件可为列表，或`{"links":[],"timeAnchors":{}}`。每条关联需稳定id、from/to、relation、reviewer、reason；撤回用relation=revoke和target。时间锚点键为factId，值有date/reason/reviewer；只对明确的今天/明天/后天解析日期，不补时区与时刻。未锚定不进入日历。原始线索账本`tasks.json/actions.md`保留兼容，关联后的主入口是`task-graph.json/task-tracking.md`。历史位于`记忆库/运行/产品功能/task-history.jsonl`和`task-versions/`。

## 问答处理

```bash
python3 scripts/soundlog_library.py ask '当时答应发送什么资料？' --query 仿真 --query 资料
python3 scripts/soundlog_library.py question-state --question 实际编号 --state processing
python3 scripts/soundlog_library.py question-expand --question 实际编号 --query '项目 资料'
python3 scripts/soundlog_library.py answer --question 实际编号 --file 回答.json
```

问题日期记录为上海时区的提问日期，用于理解问题中的“昨天”；原始录音仍不擅补时区。相对问题必须先明确检索日期，不能把问题时间当录音事件时间。自然语言整句可能零命中，agent应提取词和同义表达，在原编号上扩展检索。每词保留实际匹配总数及返回上限；不以零命中证明从未提过。回答前读引文和邻接原文，区分历史/当前、媒体/本人、计划/执行。界面不会自行调用agent登录态；等待结果将按下一次agent运行返回。

回答JSON含questionId、reviewer、status（answered或unknown）、claims、unknown。每项claim含text和evidence（id/quote）；unknown回答不虚构claim。原始请求及扩展证据有校验绑定，回答不可静默覆盖，需新版本。文件位于`记忆库/运行/自动管线/questions/<id>/`，包含request.json、可选retrieval.json与版本、answer.md/json及运行状态。

六例回归为同一agent在既有材料上先冻结问题、再查证回答的事后回归，不是独立盲测。七个预期证据ID检索到7/7；四例有证据回答、两例保留未知。同一agent对照中四例回答有支持，未发现无依据回答；这不是全库召回率或独立准确率。分离的流程讨论片段用于防止伪造冲突；未找到能确认同一事项的真实矛盾时不编造真实冲突案例。冲突并列的确定性行为另由合成测试覆盖。

## 知识、规整与创作

```bash
python3 scripts/soundlog_features.py derive --spec 派生方案.json
python3 scripts/soundlog_pipeline.py finish --spec 合并派生方案.json --links 合并事项关联.json
```

派生方案含schemaVersion=1、reviewer、sourceResultId、topics、topicRelations、cleanDocuments、marks、intents、writingPlans；详细字段以验证器与本机已保存方案为准。新增批次合并已有有效主题与关联，不能用空方案跳过尚未阅读材料。每个主题和段落引用实际fact；儿童/成人禁止混用。关系只表达共同主题、补充、矛盾或问题，不能凭共现生成因果。新增联想单列。

规整稿绑定完整原句并留差异，程序保护否定、条件、相对日期与数值；最终语义仍须agent对照。MARK按明确口令、引用、非指令或未知分类；意图始终是草稿。历史录音中的“发给他”不构成今天对外发送授权。写作提纲只用录音支持的素材，扩写建议须显式标明。图形生成不覆盖原文。

## 跨助手只读接口

运行`scripts/soundlog_mcp.py`，使用标准输入输出的逐行JSON-RPC；标准输出只有协议消息。工具为soundlog_status、soundlog_search、soundlog_day、soundlog_task、soundlog_topic、soundlog_evidence。搜索可带date，多个空白分隔词按AND匹配，同时返回原文；身份归属只对明确确认的单个fact有效。

支持stdio MCP客户端可手动配置如下（替换项目路径，具体配置位置按客户端约定）：

```json
{"mcpServers":{"soundlog":{"command":"python3","args":["/absolute/path/to/soundlog/scripts/soundlog_mcp.py","--root","/absolute/path/to/soundlog"]}}}
```

本版没有改动其他助手配置或向新应用授予数据权限。协议采用2024-11-05版本，参考[stdio传输](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports)和[工具协议](https://modelcontextprotocol.io/specification/2024-11-05/server/tools)。只读接口返回资料供调用助手处理，不自行生成无依据答案。

## 受控写入与日历

`soundlog_integrations.py --help`列出memory-prepare、memory-apply、memory-confirm、memory-reconcile，action-draft、action-execute、action-revoke与identity。

记忆写入先形成目标根、project、namespace和逐操作内容哈希的具体计划，获得相应操作批准，核对实时MCP项目及目标；apply不等于成功归档。必须真实MCP读回路径/标识/checksum并与磁盘比较后confirm。遇到中断先reconcile识别已写/未写/冲突，不覆盖未知文件。更正保留旧版本，撤回写状态墓碑，不让旧内容冒充当前；confirmed必须有用户确认依据。全部embed:false，不运行向量模型。正式范围仍仅限用户已授权的两日224篇试点，新增通用适配器验证使用独立合成库。

日历草稿需具体日历、标题、带时区的起止时间和来源。具体事件授权与计划哈希绑定，真实应用还需显式`--allow-live`；失败回执不称成功。确定标记和应用读回防止重试重复，撤销另有授权及应用核验。本次用户授权的测试已经完成创建、读回、重试和撤销，空测试日历保留；没有留下测试事件。

## 复验

```bash
python3 -m unittest discover -s Tests/ProductTests -q
python3 -m unittest discover -s Tests/SceneTests -q
python3 -m unittest discover -s Tests/MemoryTests -q
git diff --check
```

本机证据目录`记忆库/运行/产品功能/`包括qa-regression-frozen/results.json、readonly-mcp-acceptance.json、mcp-exchange-isolated/live-mcp-readback.json、real-e2e/e2e-result.json和actions下的真实日历回执。目录是本机私有验收材料，不随公开代码发布。

## 跨天和每周复盘（2026-11-16新增）

工作台新增“跨天与每周复盘”入口，复用已有日交付，无需重新转写。支持1—366天自定义范围，显示已交付日期、缺失日期、栏目数量和逐日概括；缺失日期不等于没有活动。

```bash
python3 scripts/soundlog_features.py review --from 2026-11-09 --to 2026-11-15
python3 scripts/soundlog_features.py review --from 2026-11-09 --to 2026-11-15 --spec 经审阅复盘.json
```

第一条只生成明确标记的证据索引；第二条发布agent写出的有依据复盘。方案字段为start、end、reviewer、sections；每段含title、text、category（work/life/actions/child_learning/adult_learning）、factIds。引用必须来自该范围内已保留的内容，儿童/成人学习不混用；结论仍须agent对照原文。每段回链内容卡及逐字原文、时间、文件和偏移。

不可变版本位于`产出/自动交付/reviews/review-编号/`，包含README.md、review.json、material.json、receipt.json；范围目录在reviews/catalog.json。重复运行复用同版本；源交付变动生成新版本，已审阅版本不会被仅有统计的索引静默替换。返回reviewNeedsRefresh表示旧复盘引用的日交付发生变化，须重新审阅。无已交付日期时拒绝生成空复盘。

首份真实产物覆盖11月9—15日，已交付6天，15日缺资料；精选工作、生活、历史承诺、儿童和成人学习五栏，逐条检查10项素材引文。它是精选回顾，不代表全周全部候选细节已独立验收，历史事项不转成当前待办。
