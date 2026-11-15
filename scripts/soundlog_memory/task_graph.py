"""Reviewed task associations, reversible links and evidence-state timelines."""
import hashlib
import json
from pathlib import Path
from datetime import date,timedelta
from .store import write_json, atomic
from .library_tools import library

RELATIONS = {'same_task', 'possible_same_task', 'contradicts', 'unrelated', 'revoke'}
STATE_LABELS = {'request':'提出要求','commitment':'作出承诺','proposal':'建议或备选',
                'reported_completed':'原话称已完成','reported_cancelled':'原话称取消',
                'reported_rescheduled':'原话称改期','question':'提出疑问','unknown':'状态未明',None:'未明确状态'}


def resolve_due(text, anchor):
    if not anchor:return {'text':text,'date':None,'basis':'无明确事件日期锚点'}
    if not anchor.get('reason') or not anchor.get('reviewer'):raise ValueError('时间锚点须有依据与审阅者')
    d=date.fromisoformat(anchor['date']);offset={'今天':0,'明天':1,'后天':2}.get(text)
    return {'text':text,'date':(d+timedelta(days=offset)).isoformat() if offset is not None else None,
            'basis':anchor,'boundary':'仅日期解析，不附加未提供的时区或具体时刻。'}


def build_task_graph(delivery, links, anchors=None):
    if isinstance(links,dict):
        if set(links)-{'links','timeAnchors'}:raise ValueError('事项方案字段无效')
        anchors=links.get('timeAnchors',{});links=links.get('links',[])
    if not isinstance(links,list):raise ValueError('事项关联必须为数组')
    facts = {f['id']:f for f in library(delivery) if 'actions' in f.get('selectedCategories', f['functionUses'])}
    anchors=anchors or {}
    if set(anchors)-set(facts):raise ValueError('时间锚点引用未知事项')
    parent = {k:k for k in facts}
    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]; k = parent[k]
        return k
    seen = set(); valid = []
    for link in links:
        if link.get('id') in seen or not isinstance(link.get('id'), str): raise ValueError('事项关联ID缺失或重复')
        seen.add(link['id'])
        if link.get('relation') not in RELATIONS or not link.get('reviewer') or not link.get('reason'):raise ValueError('事项关联缺少关系、审阅者或理由')
        if link['relation'] == 'revoke':
            if link.get('target') not in {r['id'] for r in valid if r['relation']!='revoke'}:raise ValueError('撤回对象不存在或是撤回记录；恢复时提交新的关联')
        else:
            if link.get('from') not in facts or link.get('to') not in facts or link['from']==link['to']:raise ValueError('关联引用的事项无效')
        valid.append(link)
    revoked = {r['target'] for r in valid if r['relation']=='revoke'}
    active = [r for r in valid if r['id'] not in revoked and r['relation']!='revoke']
    for link in active:
        if link['relation']=='same_task':
            a,b=find(link['from']),find(link['to']);parent[b]=a
    groups={}
    for fid,f in facts.items():groups.setdefault(find(fid),[]).append(f)
    tasks=[]
    for members in groups.values():
        members.sort(key=lambda f:(f['recordedStart'],f['id']))
        # ID anchors the earliest source statement, independent of which linked statement was edited.
        tid='task-'+members[0]['id'][5:]
        ids={f['id'] for f in members}
        conflicts=[l for l in active if l['relation']=='contradicts' and (l['from'] in ids or l['to'] in ids)]
        latest=members[-1]; state=latest.get('taskState') or 'unknown'
        tasks.append({'id':tid,'factIds':[f['id'] for f in members],
                      'recordedLatestState':state,'currentState':'unknown',
                      'stateLabel':'存在冲突' if conflicts else STATE_LABELS[state],
                      'currentStateExplanation':'最新录音表述只说明当时状态；现时状态未另行核验。',
                      'timeline':[{'factId':f['id'],'recordedStart':f['recordedStart'],'date':f['date'],
                                   'state':f.get('taskState'),'dueText':f.get('dueText'),
                                   'resolvedDue':resolve_due(f.get('dueText'),anchors.get(f['id'])),
                                   'summary':f['summary'],'evidence':f['evidence'],'bundle':f['bundle']} for f in members],
                      'links':[l for l in active if l.get('from') in ids or l.get('to') in ids],
                      'conflicts':conflicts})
    tasks.sort(key=lambda t:t['timeline'][0]['recordedStart'])
    return {'schemaVersion':1,'tasks':tasks,'links':valid,'boundary':'关联由agent或用户审阅记录，不由关键词自动合并。最新状态是历史原话状态。'}


def publish_task_graph(delivery, home, links, anchors=None):
    result=build_task_graph(delivery,links,anchors)
    digest=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    base=Path(home)/'task-versions';base.mkdir(parents=True,exist_ok=True)
    path=base/(digest+'.json')
    if not path.exists():write_json(path,result)
    history=Path(home)/'task-history.jsonl'
    # Append an immutable graph version; repeat execution does not duplicate a history entry.
    existing={json.loads(line)['version'] for line in history.read_text().splitlines()} if history.exists() else set()
    if digest not in existing:
        with history.open('a') as stream:stream.write(json.dumps({'version':digest,'file':str(path),'links':len(result['links'])},ensure_ascii=False)+'\n')
    write_json(Path(delivery)/'task-graph.json',result)
    lines=['# 跨天事项跟踪','','关联须有审阅依据；每条时间线可回查。当前状态未经另行核实，不能把没有新录音解释为未完成。','']
    for t in result['tasks']:
        lines += ['## '+t['id'], '', '最近录音表述：'+t['stateLabel']+'；当前状态：未知。','']
        for event in t['timeline']:
            lines += ['### '+event['recordedStart'], '', event['summary'], '', '当时性质：'+STATE_LABELS[event['state']]+'；期限原话：'+str(event['dueText'] or '未提及'),'']
            for e in event['evidence']:
                lines += [f"- [原文]({event['bundle']}/{event['date']}/sources.md#{e['id']}) · {e['startOffsetSeconds']}秒"]
        for link in t['links']:lines += ['', '关联说明：'+link['reason']+'（'+link['relation']+'）']
        lines.append('')
    atomic(Path(delivery)/'task-tracking.md','\n'.join(lines)+'\n')
    return {'version':digest,'tasks':len(result['tasks']),'reviewedLinks':len(result['links'])}
