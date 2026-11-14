"""Auditable, model-neutral four-function extraction; no memory store writes."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .evidence import canonical, chunks, day_bounds, digest, read_json, timestamp, overlaps
from .scenes import FUNCTION_PROMPT, digest_bytes, resolve_snapshot
from .store import normalize, now, write_json

VERSION = 'soundlog-products-v1.1-context'
FUNCTIONS = {'journal': '每日记录', 'minutes': '讨论纪要', 'actions': '待办与安排候选', 'learning': '学习与灵感笔记'}
ASSERTIONS = {'explicit', 'reported', 'suggestion', 'question', 'negated', 'uncertain', 'hypothetical'}
ASSERTION_LABELS = {'explicit':'原话明确表达','reported':'转述/自述线索','suggestion':'建议或意向','question':'疑问','negated':'否定','uncertain':'含糊待核实','hypothetical':'假设举例'}
TASK_LABELS = {'question':'待澄清的问题','proposal':'建议/备选意向','request':'提出的要求','commitment':'当时的承诺','reported_completed':'原话称已完成','reported_cancelled':'原话称已取消','reported_rescheduled':'原话称已改期','unknown':'状态未知'}
TASK_STATES = {'question', 'proposal', 'request', 'commitment', 'reported_completed', 'reported_cancelled', 'reported_rescheduled', 'unknown'}
PROMPT = FUNCTION_PROMPT + '''
contextUtterances是邻近参考，不计入本块已处理覆盖。可以引用上下文，但每条事实至少有一条本块utterances引文；不能仅凭邻块内容重复造条目。
只返回JSON，每块为 {key,facts:[],coverage:[]}。优先处理focusFunctions，允许跨功能标签。一条事实可供多功能使用，不重复制造事实。
facts每项字段：summary(忠于原文的简洁摘要)，functionUses(journal/minutes/actions/learning数组)，assertion(explicit/reported/suggestion/question/negated/uncertain/hypothetical)，subject(null或引文中的主体线索/文件范围声音标签)，sourceMedium(固定unknown)，eventTimeText(null或事件时间原话)，dueText(null或期限原话)，taskState(无actions时null，否则question/proposal/request/commitment/reported_completed/reported_cancelled/reported_rescheduled/unknown)，evidence([{id,quote}])。
引用只能来自该块材料且quote逐字匹配。事件时间只保留原话，不能拿录音时间代替。subject为“我”也只表示匿名原话的我，不能解释为录音持有人。
coverage逐项列出该块所有不同证据ID：{id,disposition:used/context/unclear/no_function_content,reason}；used必须被facts引用，其他必须说明未提炼原因。
不确定时可以facts=[]，但要完成coverage；不得用空数组冒充没读。明确的“比如说”保留假设，疑问不写成承诺，未决定的备选不写成日程，含糊术语不补造。
外壳 {schemaVersion:1,requestId:原值,processor:实际处理者,results:[块结果]}。所有结果仍为candidate，绝不自动确认身份、状态或执行任务。'''


def checked_read(snapshot, name, receipt):
    path = snapshot / name
    if name not in receipt['artifacts'] or not path.is_file() or digest_bytes(path) != receipt['artifacts'][name]:
        raise ValueError('来源快照文件缺失或改变: ' + name)
    return read_json(path)


def text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 6000:
        raise ValueError(field + ' 必须为非空文字且不超过6000字')
    return value


def function_uses(value):
    if not isinstance(value, list) or not value or any(not isinstance(v, str) or v not in FUNCTIONS for v in value):
        raise ValueError('functionUses 必须为有效的非空功能数组')
    return sorted(set(value))


def validate_fact(raw, item):
    allowed = {'summary', 'functionUses', 'assertion', 'subject', 'sourceMedium', 'eventTimeText', 'dueText', 'taskState', 'evidence'}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ValueError('事实包含未知字段；不得提交确认状态或归属结果')
    summary = text(raw.get('summary'), 'summary')
    uses = function_uses(raw.get('functionUses'))
    assertion = raw.get('assertion')
    if assertion not in ASSERTIONS:
        raise ValueError('assertion 无效')
    if raw.get('sourceMedium') != 'unknown':
        raise ValueError('首版来源媒介只能为unknown，不自动判断现场或外放')
    refs = raw.get('evidence')
    if not isinstance(refs, list) or not refs:
        raise ValueError('事实必须引用原文')
    excerpts = {}
    core_ids = {e['id'] for e in item['material']['utterances']}
    for ev in item['material']['utterances'] + item['material'].get('contextUtterances', []):
        excerpts.setdefault(ev['id'], []).append(ev)
    validated = {}
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {'id', 'quote'} or ref.get('id') not in excerpts:
            raise ValueError('引用超出本块材料或字段无效')
        quote = text(ref.get('quote'), 'quote')
        ev = next((e for e in excerpts[ref['id']] if quote in e['text']), None)
        if ev is None:
            raise ValueError('引文不是本块原文的逐字片段')
        # Only immutable evidence fields, never a model-provided path/time.
        validated[(ref['id'], quote)] = {**ev, 'quote': quote, 'contextOnly': ev['id'] not in core_ids}
    refs = list(validated.values())
    if not any(e['id'] in core_ids for e in refs):
        raise ValueError('事实不能只引用邻块上下文，须锚定本块证据')
    quoted = '\n'.join(e['quote'] for e in refs)
    speakers = {s for e in refs for s in e['speakers']}
    subject = raw.get('subject')
    if subject is not None and (not isinstance(subject, str) or not subject.strip() or (subject not in quoted and subject not in speakers)):
        raise ValueError('主体无原话/匿名标签依据')
    for field in ('dueText', 'eventTimeText'):
        value = raw.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip() or value not in quoted):
            raise ValueError(field + ' 必须来自引文，不自动猜日期')
    state = raw.get('taskState')
    if 'actions' in uses:
        if state not in TASK_STATES:
            raise ValueError('待办栏目必须保留事项性质/状态')
        permitted = {'question': {'question', 'unknown'}, 'suggestion': {'proposal', 'unknown'},
                     'hypothetical': {'proposal', 'unknown'}, 'negated': {'reported_cancelled', 'unknown'},
                     'uncertain': {'unknown'}}
        if assertion in permitted and state not in permitted[assertion]:
            raise ValueError('疑问、建议、假设或不确定内容不能升级为确定承诺')
        if state in {'commitment', 'request'} and assertion != 'explicit':
            raise ValueError('请求/承诺需explicit原话，仍不代表持有人或当前待办')
    elif state is not None:
        raise ValueError('非待办栏目taskState应为null')
    fact = {'summary': summary, 'functionUses': uses, 'assertion': assertion, 'subject': subject,
            'sourceMedium': 'unknown', 'eventTimeText': raw.get('eventTimeText'), 'dueText': raw.get('dueText'),
            'taskState': state, 'date': item['date'], 'status': 'candidate',
            'recordedStart': min(e['start'] for e in refs), 'recordedEnd': max(e['end'] for e in refs),
            'evidence': sorted(refs, key=lambda e: (e['start'], e['id'], e['quote']))}
    identity = {k: v for k, v in fact.items() if k not in {'functionUses', 'summary', 'status'}}
    identity['summary'] = normalize(summary)
    identity['evidence'] = sorted([{'id': e['id'], 'quote': e['quote']} for e in refs],
                                  key=lambda e: (e['id'], e['quote']))
    fact['id'] = 'fact-' + digest(identity)[:24]
    return fact


def validate_block(result, item):
    if not isinstance(result, dict) or set(result) != {'key', 'facts', 'coverage'}:
        raise ValueError('每块必须有key/facts/coverage，且不能有其他字段')
    if result['key'] != item['key'] or not isinstance(result['facts'], list):
        raise ValueError('块编号或facts无效')
    facts = [validate_fact(f, item) for f in result['facts']]
    used = {e['id'] for f in facts for e in f['evidence']}
    expected = {e['id'] for e in item['material']['utterances']}
    coverage = result['coverage']
    if not isinstance(coverage, list):
        raise ValueError('coverage须为数组')
    seen = set()
    for row in coverage:
        if not isinstance(row, dict) or set(row) != {'id', 'disposition', 'reason'}:
            raise ValueError('覆盖记录字段无效')
        key = row['id']
        if key not in expected or key in seen or row['disposition'] not in {'used', 'context', 'unclear', 'no_function_content'}:
            raise ValueError('覆盖记录越界、重复或分类无效')
        seen.add(key)
        text(row['reason'], '覆盖原因')
        if (row['disposition'] == 'used') != (key in used):
            raise ValueError('used标记与实际引用不一致')
    if seen != expected:
        raise ValueError('存在未说明处理情况的证据')
    return facts


def export_request(scenes, root, *, days=None, selections=None, time_ranges=None, max_chars=12000, context_count=2):
    if sum(v is not None for v in (days, selections, time_ranges)) > 1:
        raise ValueError('日期、选段和时段范围只能指定一种')
    if type(context_count) is not int or not 0 <= context_count <= 5:
        raise ValueError('上下文句数须为0—5')
    parsed_ranges = []
    if time_ranges is not None:
        if not isinstance(time_ranges, list) or not time_ranges:
            raise ValueError('时段范围不能为空')
        for r in time_ranges:
            start, end = timestamp(r['from']), timestamp(r['until'])
            if start >= end:
                raise ValueError('时段结束必须晚于开始，不加时区')
            parsed_ranges.append((start, end))
    snapshot = resolve_snapshot(scenes)
    root = Path(root).resolve()
    if root == snapshot or snapshot in root.parents or root in snapshot.parents:
        raise ValueError('功能输出必须与来源快照目录分离')
    receipt = read_json(snapshot / 'receipt.json')
    if receipt['state'] != 'completed':
        raise ValueError('只能从完整来源快照导出')
    available = {name[:10] for name in receipt['artifacts'] if name.endswith('_utterances.json')}
    chosen = sorted(set(days) if days is not None else available)
    if selections is not None:
        chosen = sorted({s['date'] for s in selections})
    if parsed_ranges:
        chosen = [d for d in sorted(available)
                  if any(overlaps(a, b, *day_bounds(d)) for a, b in parsed_ranges)]
    if not chosen:
        raise ValueError('没有待导出日期')
    items = []
    for day in chosen:
        day_bounds(day)
        doc = checked_read(snapshot, day + '_utterances.json', receipt)
        evidence = {e['id']: e for e in doc['utterances']}
        if selections is not None:
            for selection in [s for s in selections if s['date'] == day]:
                ids = selection['evidenceIds']
                if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or set(ids) - set(evidence):
                    raise ValueError('选择证据为空、重复或不在来源日期')
                key = text(selection['key'], 'key')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', key):
                    raise ValueError('选择编号无效')
                focus = function_uses(selection.get('focusFunctions', list(FUNCTIONS)))
                items.append({'key': key, 'date': day, 'material': {'date': day, 'focusFunctions': focus,
                              'utterances': [evidence[i] for i in ids]}})
        else:
            selected = [e for e in evidence.values() if not parsed_ranges or any(
                overlaps(timestamp(e['start']), timestamp(e['end']), a, b) for a, b in parsed_ranges)]
            for c in chunks({'date': day, 'utterances': selected, 'acoustics': []}, max_chars=max_chars):
                items.append({'key': day + '-' + c['id'], 'date': day,
                              'material': {**c['material'], 'focusFunctions': list(FUNCTIONS)}})
        # Context is taken from immutable source evidence, separately from core coverage.
        ordered = doc['utterances']
        positions = {e['id']: n for n, e in enumerate(ordered)}
        for item in [i for i in items if i['date'] == day]:
            core = item['material']['utterances']
            indices = [positions[e['id']] for e in core]
            before, after = min(indices), max(indices)
            nearby = ordered[max(0, before-context_count):before] + ordered[after+1:after+1+context_count]
            core_ids = {e['id'] for e in core}
            lo, hi = min(timestamp(e['start']) for e in core), max(timestamp(e['end']) for e in core)
            context, omitted, chars = [], [], 0
            for e in nearby:
                distance = max((lo-timestamp(e['end'])).total_seconds(), (timestamp(e['start'])-hi).total_seconds(), 0)
                if e['id'] in core_ids or distance > 90:
                    continue
                if chars + len(canonical(e)) > 6000:
                    omitted.append(e['id'])
                    continue
                context.append(e); chars += len(canonical(e))
            item['material']['contextUtterances'] = context
            item['material']['omittedContextIds'] = omitted
    for start, end in parsed_ranges:
        if not any(overlaps(timestamp(e['start']), timestamp(e['end']), start, end)
                   for item in items for e in item['material']['utterances']):
            raise ValueError('指定时段没有文字证据，不能将其标为已处理: '+start.isoformat())
    if not items or len({i['key'] for i in items}) != len(items):
        raise ValueError('没有文字块或块编号重复')
    request = {'schemaVersion': 1, 'promptVersion': VERSION, 'sourceSnapshotId': receipt['snapshotId'],
               'sourceSnapshot': str(snapshot), 'scope': 'time-range' if time_ranges is not None else ('selection' if selections is not None else 'full-date-request'),
               'timeRanges': time_ranges, 'contextCount': context_count,
               'promptSHA256': digest(PROMPT), 'items': items}
    rid = 'prodreq-' + digest(request)[:24]
    location = Path(root).resolve() / 'requests' / rid
    request['requestId'] = rid
    if location.exists():
        if read_json(location / 'request.json') != request:
            raise ValueError('已有请求被修改')
        return {'requestId': rid, 'directory': str(location), 'chunks': len(items), 'execution': 'reuse'}
    location.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.request-', dir=location.parent))
    try:
        write_json(stage/'request.json', request)
        write_json(stage/'materials.json', {'requestId': rid, 'items': items})
        write_json(stage/'result-template.json', {'schemaVersion': 1, 'requestId': rid, 'processor': '填写实际处理者',
                    'results': [{'key': i['key'], 'facts': [], 'coverage': []} for i in items]})
        (stage/'instructions.md').write_text(PROMPT + '\n', encoding='utf-8')
        os.rename(stage, location)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {'requestId': rid, 'directory': str(location), 'chunks': len(items), 'execution': 'generated'}


def load_request(root, rid):
    if not isinstance(rid, str) or not re.fullmatch(r'prodreq-[a-f0-9]{24}', rid):
        raise ValueError('功能提炼请求编号无效')
    request = read_json(Path(root)/'requests'/rid/'request.json')
    if rid != 'prodreq-' + digest({k: v for k, v in request.items() if k != 'requestId'})[:24]:
        raise ValueError('请求材料快照已改变')
    return request


def render_function(day, function, facts, *, partial, processed, total, scope, time_ranges=None):
    lines = [f'# {day} · {FUNCTIONS[function]}', '',
             f'> 机器稿语义整理候选；已处理材料块 {processed}/{total}。' + ('存在缺块，不能当作全天完成。' if partial else ''),
             '> 材料范围：' + ('局部选段试验，不代表全天。' if scope != 'full-date-request' else '所选日期全量机器转写。'),
             '> 人物身份、事件实际发生时间及历史事项当前完成状态未经确认；以下钟表时间是录到原话的时间。', '']
    if time_ranges:
        relevant = [r for r in time_ranges if overlaps(timestamp(r['from']), timestamp(r['until']), *day_bounds(day))]
        lines += ['请求时段：' + '；'.join(r['from'] + ' — ' + r['until'] for r in relevant), '']
    selected = [f for f in facts if f['date'] == day and function in f['functionUses']]
    if not selected:
        lines += ['本次已处理材料中未提炼出本栏目条目；原因及逐句处理记录见coverage.json。', '']
    for fact in sorted(selected, key=lambda f: (f['recordedStart'], f['id'])):
        lines += [f"## 录音 {fact['recordedStart'][11:]} · {ASSERTION_LABELS[fact['assertion']]}" , '']
        lines += ['> ' + s for s in fact['summary'].split('\n')]
        lines += ['', f"条目 `{fact['id']}`；归属：{fact['subject'] or '未知'}；来源媒介：未知。"]
        if fact['taskState']:
            lines.append('事项性质/状态：' + TASK_LABELS[fact['taskState']] + '（只代表当时原话，不代表当前任务状态）。')
        lines += ['期限原话：' + (fact['dueText'] or '未明确'), '事件时间原话：' + (fact['eventTimeText'] or '未明确'), '']
        for ev in fact['evidence']:
            lines += [f"- 证据 `{ev['id']}` · `{ev['sourceFile']}` · {ev['startOffsetSeconds']}—{ev['endOffsetSeconds']}秒 · {'邻近参考' if ev.get('contextOnly') else '本块证据'} · 匿名候选 `{', '.join(ev['sourceFile'] + '@' + ev['sourceSHA256'][:12] + ':' + s.rsplit(':', 1)[-1] for s in ev['speakers']) or '未匹配'}`"]
            lines += ['  > ' + s for s in ev['quote'].split('\n')]
        lines.append('')
    return '\n'.join(lines)


def import_result(root, envelope):
    root = Path(root).resolve()
    if not isinstance(envelope, dict) or set(envelope) != {'schemaVersion', 'requestId', 'processor', 'results'} or envelope['schemaVersion'] != 1:
        raise ValueError('结果外壳无效')
    processor = text(envelope.get('processor'), 'processor')
    if processor == '填写实际处理者':
        raise ValueError('请填写实际处理者')
    request = load_request(root, envelope['requestId'])
    known = {i['key']: i for i in request['items']}
    if not isinstance(envelope['results'], list):
        raise ValueError('results须为数组')
    all_facts, coverage, seen = {}, [], set()
    input_fact_count = 0
    # Validate everything before writing any result or changing a default.
    for result in envelope['results']:
        key = result.get('key') if isinstance(result, dict) else None
        if not isinstance(key, str) or key not in known or key in seen:
            raise ValueError('未知或重复块编号')
        seen.add(key)
        facts = validate_block(result, known[key])
        input_fact_count += len(facts)
        coverage.append({'key': key, 'date': known[key]['date'], 'evidence': result['coverage']})
        for fact in facts:
            if fact['id'] in all_facts:
                fact['functionUses'] = sorted(set(fact['functionUses'] + all_facts[fact['id']]['functionUses']))
            all_facts[fact['id']] = fact
    missing = sorted(set(known)-seen)
    state = 'partial' if missing else 'completed'
    facts = sorted(all_facts.values(), key=lambda f: (f['date'], f['recordedStart'], f['id']))
    result_id = 'product-' + digest({'envelope': envelope, 'implementation': digest_bytes(Path(__file__))})[:24]
    results = root/'results'
    results.mkdir(parents=True, exist_ok=True)
    destination = results/result_id
    with (root/'.import.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('功能结果正在导入') from None
        stage = Path(tempfile.mkdtemp(prefix='.product-', dir=results))
        try:
            write_json(stage/'input.json', envelope)
            write_json(stage/'facts.json', {'facts': facts, 'status': 'candidate'})
            write_json(stage/'coverage.json', {'processed': coverage, 'missingChunks': missing})
            days = sorted({i['date'] for i in request['items']})
            lines = ['# 录音功能提炼试用结果', '',
                     f'状态：{state}；请求块 {len(seen)}/{len(known)}；候选条目 {len(facts)}。', '',
                     '材料范围：' + ('局部选段试验，不代表全天处理完成。' if request['scope'] != 'full-date-request' else '所选日期全量机器转写。'), '',
                     '不是已确认个人事实，未写入正式Basic Memory。没有听音校订。', '',
                     '| 日期 | 每日记录 | 讨论纪要 | 待办与安排 | 学习与灵感 |', '|---|---|---|---|---|']
            for day in days:
                day_total = sum(i['date'] == day for i in request['items'])
                processed = sum(known[k]['date'] == day for k in seen)
                for function in FUNCTIONS:
                    (stage/(day+'_'+function+'.md')).write_text(render_function(day, function, facts,
                        partial=processed != day_total, processed=processed, total=day_total, scope=request['scope'], time_ranges=request.get('timeRanges')), encoding='utf-8')
                lines.append('| '+day+' | '+' | '.join(f'[{FUNCTIONS[f]}]({day}_{f}.md)' for f in FUNCTIONS)+' |')
            (stage/'README.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
            artifacts = {p.name: digest_bytes(p) for p in stage.iterdir()}
            report = {'resultId': result_id, 'requestId': request['requestId'], 'state': state,
                      'processor': processor, 'at': now(), 'missingChunks': missing,
                      'processedChunks': len(seen), 'totalChunks': len(known), 'facts': len(facts),
                      'byFunction': {f: sum(f in fact['functionUses'] for fact in facts) for f in FUNCTIONS},
                      'sourceSnapshot': request['sourceSnapshot'], 'sourceSnapshotId': request['sourceSnapshotId'],
                      'promptSHA256': request['promptSHA256'], 'implementationSHA256': digest_bytes(Path(__file__)),
                      'artifacts': artifacts, 'semanticAssessment': 'not_automatically_verified',
                      'scope': request['scope'], 'timeRanges': request.get('timeRanges'),
                      'uniqueCoreUtterances': len({e['id'] for i in request['items'] for e in i['material']['utterances']}),
                      'processedCoreUtterances': len({e['id'] for k in seen for e in known[k]['material']['utterances']}),
                      'inputFacts': input_fact_count, 'duplicateFactsRemoved': input_fact_count-len(facts),
                      'contextReferences': sum(e.get('contextOnly', False) for f in facts for e in f['evidence'])}
            write_json(stage/'receipt.json', report)
            reused = destination.exists()
            if reused:
                old = read_json(destination/'receipt.json')
                if old['artifacts'] != artifacts or any(digest_bytes(destination/name) != sha for name,sha in artifacts.items()):
                    raise ValueError('旧结果已改变，拒绝复用或覆盖')
            else:
                os.rename(stage, destination)
            # Request-local completion only; a sample can never replace an all-day result.
            if not missing:
                write_json(root/'completed'/ (request['requestId']+'.json'), {'result': str(destination), 'resultId': result_id})
            return {**report, 'directory': str(destination), 'execution': 'reuse' if reused else 'generated'}
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def combine_results(root, envelopes):
    """Assemble partial batches; reject conflicting revisions instead of overwriting."""
    if not isinstance(envelopes, list) or not envelopes:
        raise ValueError('至少提供一份分批结果')
    rid = envelopes[0].get('requestId') if isinstance(envelopes[0], dict) else None
    request = load_request(root, rid)
    known = {i['key']: i for i in request['items']}
    combined, processors, sources = {}, set(), []
    for env in envelopes:
        if not isinstance(env, dict) or set(env) != {'schemaVersion','requestId','processor','results'} or env['schemaVersion'] != 1 or env['requestId'] != rid:
            raise ValueError('分批结果须属于同一请求，且格式正确')
        processor = text(env['processor'], 'processor')
        if processor == '填写实际处理者' or not isinstance(env['results'], list):
            raise ValueError('分批处理者或results无效')
        processors.add(processor)
        seen = set()
        for block in env['results']:
            key = block.get('key') if isinstance(block, dict) else None
            if not isinstance(key, str) or key not in known or key in seen:
                raise ValueError('分批内块未知或重复')
            seen.add(key)
            validate_block(block, known[key])
            if key in combined and combined[key] != block:
                raise ValueError('同一块存在不同修订，拒绝静默覆盖: '+key)
            combined[key] = block
        sources.append({'sha256': digest(env), 'processor': processor, 'chunks': sorted(seen)})
    envelope = {'schemaVersion': 1, 'requestId': rid, 'processor': ' / '.join(sorted(processors)),
                'results': [combined[i['key']] for i in request['items'] if i['key'] in combined]}
    report = {'requestId': rid, 'sources': sources, 'processedChunks': len(combined),
              'totalChunks': len(known), 'missingChunks': sorted(set(known)-set(combined)),
              'envelopeSHA256': digest(envelope)}
    return envelope, report


def rebase_completed_results(root, target_request_id, source_result_ids):
    """Reuse completed reviews only when every source block exactly matches a target block."""
    root = Path(root).resolve()
    if (not isinstance(source_result_ids, list) or not source_result_ids
            or any(not isinstance(rid, str) for rid in source_result_ids)
            or len(source_result_ids) != len(set(source_result_ids))):
        raise ValueError('来源结果编号须为非空且无重复的字符串列表')
    target = load_request(root, target_request_id)
    target_items = {item['key']: item for item in target['items']}
    if len(target_items) != len(target['items']):
        raise ValueError('目标请求含重复块键')
    target_contract = {key: target.get(key) for key in
                       ('promptVersion', 'promptSHA256', 'scope', 'timeRanges', 'contextCount')}
    merged, source_details, processors = {}, [], set()
    expected_by_source = set()
    from .reading import load_verified_result
    for result_id in source_result_ids:
        receipt, _ = load_verified_result(root, result_id)
        if (receipt.get('state') != 'completed'
                or receipt.get('missingChunks')
                or receipt.get('processedChunks') != receipt.get('totalChunks')):
            raise ValueError('只能迁移已完成且无缺块的来源结果: ' + result_id)
        source_request = load_request(root, receipt.get('requestId'))
        contract = {key: source_request.get(key) for key in target_contract}
        if contract != target_contract:
            raise ValueError('来源与目标请求的提示版本、范围或上下文设置不同')
        source_input = read_json(root / 'results' / result_id / 'input.json')
        if (source_input.get('requestId') != source_request['requestId']
                or source_input.get('schemaVersion') != 1
                or not isinstance(source_input.get('results'), list)):
            raise ValueError('来源结果输入与请求不匹配: ' + result_id)
        old_items = {item['key']: item for item in source_request['items']}
        if len(old_items) != len(source_request['items']):
            raise ValueError('来源请求含重复块键')
        if len(source_input['results']) != len(old_items):
            raise ValueError('来源结果并非完整请求')
        seen = set()
        for block in source_input['results']:
            key = block.get('key') if isinstance(block, dict) else None
            if not isinstance(key, str) or key not in old_items or key in seen:
                raise ValueError('来源结果包含未知或重复块键')
            seen.add(key)
            if key not in target_items or old_items[key] != target_items[key]:
                raise ValueError('来源块的原文、上下文或块定义与目标不完全一致: ' + key)
            if key in merged:
                raise ValueError('多个来源结果覆盖同一目标块: ' + key)
            validate_block(block, old_items[key])
            merged[key] = block
        if seen != set(old_items):
            raise ValueError('来源结果遗漏请求块')
        if expected_by_source & seen:
            raise ValueError('来源请求之间存在重复块')
        expected_by_source |= seen
        processors.add(source_input['processor'])
        source_details.append({'resultId': result_id, 'requestId': source_request['requestId'],
                               'sourceSnapshotId': source_request['sourceSnapshotId'],
                               'blocks': len(seen)})
    if set(merged) != set(target_items):
        raise ValueError('来源结果未完整覆盖目标请求: missing=' + str(len(set(target_items)-set(merged)))
                         + ', extra=' + str(len(set(merged)-set(target_items))))
    envelope = {'schemaVersion': 1, 'requestId': target_request_id,
                'processor': ' / '.join(sorted(processors)),
                'results': [merged[item['key']] for item in target['items']]}
    report = {'targetRequestId': target_request_id,
              'targetSnapshotId': target['sourceSnapshotId'],
              'sourceResults': source_details,
              'exactMaterialBlocks': len(merged),
              'uniqueCoreUtterances': len({e['id'] for item in target['items']
                                           for e in item['material']['utterances']}),
              'envelopeSHA256': digest(envelope)}
    return envelope, report


def request_progress(root, rid):
    """Read-only progress: exports and local drafts never count as imported work."""
    root=Path(root).resolve();request=load_request(root,rid)
    known={i['key']:i for i in request['items']};versions={};batches=0
    for path in sorted((root/'results').glob('*/receipt.json')):
        receipt=read_json(path)
        if receipt.get('requestId')!=rid:continue
        input_path=path.parent/'input.json'
        if digest_bytes(input_path)!=receipt['artifacts']['input.json']:
            raise ValueError('已导入输入文件被改变，进度不可核实')
        envelope=read_json(input_path);batches+=1
        for block in envelope['results']:
            if block['key'] not in known:raise ValueError('进度记录含越界块')
            validate_block(block,known[block['key']])
            versions.setdefault(block['key'],set()).add(digest(block))
    conflicts=sorted(k for k,v in versions.items() if len(v)>1)
    completed=root/'completed'/(rid+'.json');pointer=None
    if completed.exists():
        pointer=read_json(completed);dest=Path(pointer['result']).resolve()
        if dest.parent!=(root/'results').resolve():raise ValueError('完成引用越界')
        receipt=read_json(dest/'receipt.json')
        if receipt['requestId']!=rid or receipt['state']!='completed' or receipt['resultId']!=pointer['resultId']:
            raise ValueError('完成引用无效')
        for name,sha in receipt['artifacts'].items():
            if digest_bytes(dest/name)!=sha:raise ValueError('已完成结果文件缺失或改变')
    seen=set(versions)
    state='completed' if pointer else ('ready_to_combine' if seen==set(known) and not conflicts else ('partial' if seen else 'not_started'))
    return {'requestId':rid,'scope':request['scope'],'state':state,'importedBatches':batches,
            'importedChunks':len(seen),'totalChunks':len(known),'missingChunks':sorted(set(known)-seen),
            'uniqueCoreUtterances':len({e['id'] for i in request['items'] for e in i['material']['utterances']}),
            'importedCoreUtterances':len({e['id'] for k in seen for e in known[k]['material']['utterances']}),
            'historicalRevisionConflicts':conflicts,'completedResult':pointer,
            'semanticAssessment':'not_inferred_from_import_status',
            'boundary':'只统计本请求已校验导入的核心块；材料导出、邻近参考、本地未导入草稿、其他范围的试验不计入完成。'}
