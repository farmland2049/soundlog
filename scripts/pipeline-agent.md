# Soundlog 手动开始后的完整处理约定

运行 `python3 scripts/soundlog_pipeline.py start` 完成本机音频处理并同步每日素材。再执行 `prepare-analysis --date YYYY-MM-DD` 取得指定日期的分析请求和 `sameDaySources`。从请求目录读取原文与上下文，覆盖全部材料块，使用 `ingest` 导入结果、`publish` 发布分栏和复盘，再用 `finish` 完成派生交付。Basic Memory 当日正文由发布生成，Soundlog 界面沿用同一批成果。

## 同日资料核对

每日成果正文保存在 `soundlog/daily/`。取材使用当日来源与工作日志；旧成果仅用于核对。

每次生成每日记录、每日复盘或相关功能总结，按成果的实际自然日逐日核对。处理历史积压时查历史录音对应日期；直接受托总结指定日期时查该日期，即使该日没有录音，也可依据实际存在的文字记录完成总结。接续到筛选或扩展阶段时，若本轮未核对同日来源，先补查。

- 录音：使用 Basic Memory 的 `soundlog/sources/YYYY-MM-DD.json` 及据此生成的分析请求。既有成果可用于核对，录音引文按证据 ID 回查。
- Basic Memory：从工作区 `05-日常工具/BasicMemory/笔记/` 查 `工作日结/YYYY-MM-DD.md`、`长期记忆/事件/` 和同日直接相关的笔记。仅取与本次成果相关的段落，优先核对原始记录和明确更正。既有 Soundlog 归档与对应录音同源，去重时按同一来源处理。
- 工作管理：在本机坚果云挂载目录中打开 `工作管理/工作日志/YYYYMM.md`（macOS 挂载目录通常为 `~/Library/CloudStorage/坚果云-*/`），取对应日期段落。日期可以用紧凑月日标记，例如 11 月 26 日对应 `1126`。影响工作结论和状态时，按已有保密范围核对该条记录所指向的同日原件。

把同一事件合并表述，保留各来源提供的不同信息。外部补充在相关结论旁注明来源名称、笔记或文件路径和日期小节。明确更正以能核实的更正为准，其余冲突标明待核实；以原记录的状态和归属为准。仅把符合当前成果用途和保密范围的必要信息写入交付。查无当天记录与无法读取是两种情况，均在成果的来源说明中如实标注，继续用已核实资料交付。

发布前把跨来源日总结写入当日 `dailyReviews.overview`。后续整理纪要、交谈、事项、学习与知识、创作和跨天复盘时，按栏目用途用同日资料补充与核对。录音事实、引文、时间轴及要求录音证据的场景或事项字段仍按现有验证规则提交。仅由文字记录支持的内容放入日总结并明确出处；需要向用户另行交付某个功能总结时可引用相应文字原件。

## 历史情境核对

整理当天内容时，如果一段谈话提到既往经历、延续事项、前次方案，或同一个词可能指不同对象，先用当天的对象、时间和场景细节构造检索词：

```sh
python3 scripts/soundlog_pipeline.py history-search --date YYYY-MM-DD --term 关键词 --term 对象或旧称
```

读取返回的私有回执，打开匹配原件及邻近内容。审核事件对象、发生时间、阶段和关键细节是否一致。回忆、假设、市场比较、当场行动及最终结果分别处理。先前记录中的成交或完成只用于可核实的同一事件，不凭关键词、同一说话人候选或相似数字合并。当天证据能确认讨论主题但不能确认归属时，只呈现明确、有意义的讨论内容。

在筛选文件的 `historyChecks` 中保存本次核对。每项写入 `searchId`、当日 `factIds`、回执中的 `historicalIds`、关联判断 `outcome`（`same_event`、`different_event` 或 `insufficient`）及具体 `reason`。仅在来源支持、且与当日结果有关时，将旧背景写进发布正文。回执保留历史日期、路径和证据定位，方便复核或补录后重审。

## 筛选数据

```json
{
  "resultId": "product-由实际导入返回",
  "reviewer": "实际agent与审阅范围",
  "rows": [
    {"id":"实际fact编号", "decision":"retain", "reason":"基于具体引文的保留理由", "categories":["journal"]},
    {"id":"其他实际fact编号", "decision":"defer", "reason":"关键对象缺失，无法还原场景"}
  ]
}
```

分类允许 journal、minutes、actions、child_learning、adult_learning。前三类须在原 fact.functionUses 内；两种学习分类须有原 learning 用途。允许多用途，不重复造事实。fact不存在时仍提交空 rows，实现“已读但没有有意义内容”的完整交付。

## 首版最终交付

- `产出/自动交付/README.md`：按天导航，每个日期指向最新已完成交付包。
- 每日五份 Markdown：每日记录、讨论纪要、录音中的事项、儿童学习、成人学习与知识。
- 每日原文索引：录音起止时间、原始文件偏移、引用正文；Markdown和HTML都可回查。
- 每批 index.html：直接本机打开即可关键词检索，点原文回溯；search.json 为可复用结构化素材。
- screening.json：全部保留/暂缓决策；receipt.json：状态与全部交付文件哈希。
- 此版不提供自主执行待办、自动人物身份登记或未经检索的自然语言回答；用户在本线程问录音问题时，agent先检索交付内容并用原文回答。

Soundlog 不按时间表处理录音。工作台与命令行保留手动入口。用户启用外部存储自动处理后，独立挂载监听器在配置的录音卷接入时打开桌面应用，由界面调用同一管线。

新增日交付：筛选清单可附 dailyReviews，键为实际日期，每日含 overview（agent基于当日材料的概括）和 highlights（当日保留fact编号数组）；应实际填写，未填仅生成索引，不能称已完成每日复盘。交付器自动生成日期首页、timeline.md/json、daily-review.md/json和内容卡片，并刷新事项线索账本。事项自动跨天归并尚未实现，当前状态保持未知。

证据问答入口：`python3 scripts/soundlog_library.py ask 问题 --query 检索词` 可重复传词，默认搜索已交付内容及可用的完整原文快照。读取其目录request.json，必要时用更多词补查。回答JSON须含questionId、reviewer、status(answered/unknown)、claims（各项text与evidence的id/quote）、unknown。程序核对引用，结论仍由agent根据实际原文判断。用 `python3 scripts/soundlog_library.py answer --question 问题编号 --file 回答.json` 保存，禁止假装浏览器已能即时调用模型。

## 完整产品扩展阶段（A—F）

新批次 publish 后状态为 awaiting_enrichment，而非整个任务完成。继续阅读所有相关证据并合并维护 `记忆库/运行/产品功能/derived-spec.json` 和 `task-links.json`。派生方案含schemaVersion=1、reviewer、sourceResultId（当前resultId），topics、topicRelations、cleanDocuments、marks、intents、writingPlans；字段和约束以 `derived_products.py` 的实际验证器和已保存实例为准。生成有出处的知识卡，明确分儿童/成人；跨天关联需审阅理由，关系是主题、补充、冲突或问题，不推断因果。新增联想单独标记。规整稿绑定完整原句，保留否定、条件、时间和数字；专名不清留未知。MARK先判断是否现场指令、引用、未知或非口令；历史请求只生成draft。没有相应材料时可以为空，但必须实际读过，不能用空数组跳过有价值内容。

事项关联支持same_task、possible_same_task、contradicts、unrelated；撤回用新id、relation=revoke、target=既有关联ID。每项附reviewer和reason。只有same_task会合并，可能关联不改变状态。状态序列保留各次原话性质，不将缺少后续解释为尚未完成。保留历史版本，不删除既有更正。使用 `soundlog_pipeline.py finish --spec 合并方案.json --links 关联.json` 验证并发布，成功后才回到idle。

跨助手查询用 `soundlog_mcp.py` 的只读stdio接口；不要替用户修改助手配置或授予新数据访问。正式记忆新增操作用 `soundlog_integrations.py memory-prepare` 形成具体计划，拿到对应授权和实时MCP项目预检后才apply；必须真实MCP读回再confirm。日历请求先生成action-draft供用户审阅，收到指定目标和具体事件授权才live执行，回读匹配后记录真实回执。当前自动任务不得自行将录音历史口令当外部执行授权。

问答补查必须使用`question-expand --question 原编号 --query 检索词`，不要只另建问题让网页原请求永远等待。读取request和retrieval的完整证据，先保存processing状态，失败说明真实错误。记录提问日期供相对问题锚定，原录音不擅补时区。完成答案须保留未知及媒体边界。

日复盘dailyReviews可包含scenes数组；每项id为scene-前缀、type为work/life/child_learning/adult_learning、title、summary、factIds、sections（title/text/factIds）。所有fact须来自当日保留项，学习材料与儿童/成人类型一致。结构化场景须由实际时间与语义支持，卡片不是连续场景。MARK扫描可参考mark_scan.py读取完整原文邻接，扫描仅提示，不代表指令授权。

## 围绕本人的内容

本人声音确认后，读取`voice_calibration.my_view`及精确原文邻接，逐项维护`记忆库/运行/产品功能/personal-spec.json`；使用`soundlog_features.py personal --spec 方案.json`发布。方案schemaVersion=1、reviewer、decisions；每个决策含id、kind(commitment/request_to_me/expression/ignore)、summary、reason、selfEvidenceId、evidence(id/quote)。每项必须有用户确认的精确本人片段，不用模型疑似声纹或同号说话人扩散归属。确认撤销后，个人页面自动隐藏相应旧内容，旧版本保留。

不能把所有第一人称句子当承诺；产品想法、条件、建议和引用须根据原文判断。语义不全可ignore并写理由。交办本人须另有requestEvidenceId（用户排除本人声音）、同原文件90秒内的本人回应，以及recipientProof的reason、quote（本人回应引用）；连续性只是门槛，是否确实交办仍须agent审阅，不将对别人或媒体的要求冒充给本人。首轮允许交办栏为空。当前完成状态固定未知，本阶段不自动排期、不生成外部行动。

## 每日跨天复盘

完成新音频交付后，以最新已交付日期为范围终点，取最近7天，使用period_review.period_material读取每日概括和实际候选；依据具体引文形成精选复盘方案（字段见A-F功能使用与验收.md），再运行soundlog_features.py review --from 起日 --to 终日 --spec 方案.json。不要用统计索引假装agent跨天总结，不把全周素材未逐句复核说成完成。无新交付且已有同来源版本时不重复制造复盘；没有日期资料时不补活动。有新输入或更新的相同范围，保留旧版本并重新审阅引用。

## 面向用户的成果页面（2026-11-17）

主入口为成果页，原工作台在`/debug/`作调试后台。新交付后，当前agent须将明确内容合并为会议、交谈或事件，在私有`记忆库/运行/产品功能/`或本轮审阅目录维护成果方案，用`soundlog_features.py products --spec 方案.json`发布。不只列提炼候选；会议直接给标题、概括、纪要、结论与方向、待办清单、开口项。交谈/事件按用途简要记录；无关插话不混进会议。内容明确时自主整理，不反复交用户确认。不要把会上的待办默认派给本人，未出现负责人/期限时不补造。提案不写成通过的决议。

方案格式见`soundlog_memory/product_view.py`实际验证器：schemaVersion=1、reviewer、activities；每项id、kind(meeting/conversation/event)、date、title、summary、factIds；minutes/decisions/actions/openItems为text、factIds数组，可附有依据的owner、due。引用当日保留事实；actions仅引用事项材料。原文、文件偏移、声纹校准、哈希、筛选和运行状态保留在后台，主界面不呈现。标题是agent对场景的整理命名，不捏造正式会议名称、参会人或精确会议起止；页面时段由引用内容覆盖计算。旧成果方案需合并维护，不覆盖其他日期。语义歧义能略过就留后台原因，只把影响理解的未知简短写进成果。

产品层已发布、对应页面API可读且原文绑定核对通过后，才将本轮称为完成；新成果不自动修改日历、发送消息或扩大正式记忆写入。

## 日常归档与长期积累

每次新日交付后，按实际录音日期整理一份可独立阅读的日常记录草稿，包含有依据的生活事件、对话内容和原稿入口。将已采用的日记录作为去重基准，跨日主题按有用的新材料补充。录音中提到的安排、观点和自述用当时口径记录，无法确认归属或结果时保留边界。

日交付器为本轮日期准备归档草稿及独立状态。正式写入采用 `soundlog-YYYYMMDD-daily-review` 作为同一天的固定 ID，正文保留对应交付包的 `YYYY-MM-DD/daily-review.md` 原稿入口。根据用户授权筛选后走正式写入流程；`memory-confirm` 通过真实读回后登记归档状态。重新交付同一日期时，页面会提示既有归档待更新。

工作纪要、个人表达和事项在 Soundlog 内持续积累。使用 `产出/长期积累/` 的对应索引定位已交付原稿；本人表达只采用精确确认过的片段，历史承诺的当前状态仍须回查后续证据。工作和健康细节按已有保密及适用范围处理。正式 Basic Memory 归档复用 `memory-prepare`、写入回执和 MCP 读回，按用户授权的内容范围执行。

成果视图的发布回执记录各成果日期对应的交付包。按钮运行结束时，程序检查本轮新增或更新的日期是否指向对应交付包，且日复盘、成果证据和页面均可读。审核后没有保留内容的日期可以用有实际概括的日复盘完成交付。缺少成果页的日期如有已审阅场景，程序将其作为事件卡补发并再次核验；若同一日期的已有成果需要随新交付更新，按成果方案流程重新审阅并发布该日。
