"""Read published content, retain task evidence, and queue grounded agent answers."""
import hashlib
import json
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from .scenes import digest_bytes
from .store import write_json, atomic


def library(root):
    root = Path(root)
    catalog = json.loads((root/'catalog.json').read_text())
    facts = {}
    for day, bundle in sorted(catalog['days'].items()):
        if Path(bundle).name != bundle or not bundle.startswith('bundle-'):
            raise ValueError('交付目录越界')
        folder = root/bundle
        receipt = json.loads((folder/'receipt.json').read_text())
        if digest_bytes(folder/'search.json') != receipt['artifacts']['search.json']:
            raise ValueError('检索交付已经改变')
        for f in json.loads((folder/'search.json').read_text())['facts']:
            if f['date'] == day: facts[f['id']] = {**f, 'bundle':bundle}
    return list(facts.values())


def task_ledger(root):
    """Independent evidence-backed task mentions; never guess cross-day identity."""
    root = Path(root); facts=library(root); rows=[]
    for f in facts:
        if 'actions' not in f.get('selectedCategories',f['functionUses']): continue
        rows.append({'id':'task-'+f['id'][5:], 'factId':f['id'], 'date':f['date'],
                     'summary':f['summary'], 'recordedState':f.get('taskState'),
                     'dueText':f.get('dueText'), 'currentState':'unknown',
                     'reviewNotes':f.get('reviewNotes',''), 'evidence':f['evidence'],
                     'bundle':f['bundle'], 'association':'unlinked'})
    lines=['# 跨天事项线索账本', '', '每项是录音当时的请求、建议、承诺或状态陈述；目前不自动合并相似事项，当前完成状态保持未知。', '']
    for r in rows:
        lines += ['## '+r['date']+'｜'+r['summary'], '', '当时性质：'+str(r['recordedState'])+'；期限原话：'+str(r['dueText'] or '未提及')+'。', '', '当前状态：暂无核实；跨天关联：未认定。', '']
        if r['reviewNotes']:lines+=['用户补充：'+r['reviewNotes'], '']
        for e in r['evidence']:lines += [f"- [原文]({r['bundle']}/{r['date']}/sources.md#{e['id']}) · {e['start']}"]
        lines.append('')
    write_json(root/'tasks.json', {'rows':rows,'linking':'not_implemented','boundary':'事项线索账本，不是已证实的当前待办。'})
    atomic(root/'actions.md', '\n'.join(lines)+'\n')
    return {'mentions':len(rows),'crossDayLinks':0,'state':'mentions_only'}


def ask(root, home, question, queries, raw_snapshot=None, question_timezone="Asia/Shanghai"):
    """Prepare lexical evidence for the current agent, never invent a reply."""
    if not isinstance(question,str) or not question.strip() or not queries or any(not isinstance(q,str) or not q.strip() for q in queries):
        raise ValueError('须提供问题与至少一个检索词')
    facts=library(root)
    hits=[f for f in facts if any(q.casefold() in (f['summary']+' '+f.get('reviewNotes','')+' '+' '.join(e['quote'] for e in f['evidence'])).casefold() for q in queries)]
    raw = []
    if raw_snapshot is not None:
        from .scenes import search_evidence
        raw = [search_evidence(raw_snapshot, q, limit=1000) for q in queries]
    question_date=datetime.now(ZoneInfo(question_timezone)).date().isoformat()
    identity=hashlib.sha256(json.dumps({'question':question,'questionDate':question_date,'timezone':question_timezone,'queries':queries,'facts':hits,'raw':raw},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    folder=Path(home)/'questions'/('question-'+identity);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'request.json'
    request={'id':'question-'+identity,'question':question,'questionDate':question_date,'questionTimezone':question_timezone,'queries':queries,'facts':hits,
             'rawEvidence':raw,'scope':'retained_and_raw' if raw else 'published_retained_only','boundary':'按指定词检索；完整原文通道仅在提供快照时启用，每词最多返回1000条且保留总匹配数。同义改写可能漏检，空结果不证明从未提及。'}
    request['requestSHA256']=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if path.exists() and json.loads(path.read_text())!=request:raise ValueError('问题请求发生冲突')
    if not path.exists():write_json(path,request)
    return {'id':request['id'],'state':'answered' if (folder/'answer.json').exists() else 'awaiting_agent','matches':len(hits),'directory':str(folder)}


def answer(home, question_id, response):
    import re
    if not re.fullmatch(r'question-[a-f0-9]{24}',question_id):raise ValueError('问题编号无效')
    folder=Path(home)/'questions'/question_id;request=json.loads((folder/'request.json').read_text())
    expected=request.get('requestSHA256')
    if expected and hashlib.sha256(json.dumps({k:v for k,v in request.items() if k!='requestSHA256'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=expected:
        raise ValueError('问题材料已经改变')
    response={**response,'requestSHA256':expected}
    if response.get('questionId')!=question_id or response.get('status') not in {'answered','unknown'} or not response.get('reviewer'):
        raise ValueError('回答状态或处理者无效')
    claims=response.get('claims',[]); unknown=response.get('unknown')
    if not isinstance(claims,list) or not isinstance(unknown,str):raise ValueError('回答结构无效')
    if response['status']=='unknown' and (claims or not unknown.strip()):raise ValueError('未知回答须说明缺少什么依据')
    if response['status']=='answered' and not claims:raise ValueError('有答案须有带证据的陈述')
    extra_path=folder/'retrieval.json'
    if extra_path.exists():
        extra=json.loads(extra_path.read_text());sha=extra.pop('sha256')
        if hashlib.sha256(json.dumps(extra,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=sha or extra['originalSHA256']!=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest():
            raise ValueError('扩展检索证据已改变')
        response['retrievalSHA256']=sha
        request={**request,'facts':request['facts']+extra['facts'],'rawEvidence':request.get('rawEvidence',[])+extra['rawEvidence'],'scope':extra['scope']}
    evidence={e['id']:e for f in request['facts'] for e in f['evidence']}
    for part in request.get('rawEvidence',[]):
        evidence.update({e['id']:e for e in part['matches']})
    lines=['# '+request['question'], '', '检索范围：'+request['scope']+'；'+request['boundary'], '']
    for claim in claims:
        if not isinstance(claim.get('text'),str) or not claim['text'].strip() or not claim.get('evidence'):
            raise ValueError('回答每项须有内容及原文证据')
        lines += [claim['text'], '']
        for ref in claim['evidence']:
            original=evidence.get(ref.get('id'))
            if not original or not ref.get('quote') or ref['quote'] not in original['text']:raise ValueError('回答引用缺失或不匹配')
            lines += [f"- `{original['sourceFile']}` · {original['start']} · {original['startOffsetSeconds']} 秒", '> '+ref['quote'], '']
    lines+=['## 尚不明确', '', unknown or '未另列；回答仅限上述来源。','', '回答由所标明agent整理；引用校验不替代对结论的语义判断。']
    if (folder/'answer.json').exists():
        if json.loads((folder/'answer.json').read_text())!=response:raise ValueError('已有回答不同，须创建新问题版本')
    else:
        atomic(folder/'answer.md','\n'.join(lines)+'\n');write_json(folder/'answer.json',response)
    return {'state':'answered','answer':str(folder/'answer.md')}


def question_state(home,question_id,state,detail=''):
    import re,time
    if not re.fullmatch(r'question-[a-f0-9]{24}',question_id) or state not in {'processing','failed','awaiting_agent'}:raise ValueError('问题状态无效')
    folder=Path(home)/'questions'/question_id
    if not (folder/'request.json').exists() or (folder/'answer.json').exists():raise ValueError('问题不存在或已经回答')
    status={'state':state,'updatedAt':time.time(),'error':detail if state=='failed' else None}
    write_json(folder/'status.json',status);return status


def expand_question(root,home,question_id,queries,raw_snapshot=None):
    import re
    if not re.fullmatch(r'question-[a-f0-9]{24}',question_id):raise ValueError('问题编号无效')
    folder=Path(home)/'questions'/question_id
    if (folder/'answer.json').exists():raise ValueError('已回答问题需创建新版本，不能改动其检索证据')
    original=json.loads((folder/'request.json').read_text())
    if not queries or any(not isinstance(q,str) or not q.strip() for q in queries):raise ValueError('扩展检索词为空')
    terms=[q.strip() for q in queries]
    facts=[f for f in library(root) if any(all(part in (f['summary']+' '+' '.join(e['quote'] for e in f['evidence'])).casefold() for part in q.casefold().split()) for q in terms)]
    from .scenes import search_evidence
    raw=[search_evidence(raw_snapshot,q,limit=1000) for q in terms] if raw_snapshot is not None else []
    revision={'questionId':question_id,'originalSHA256':hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'queries':terms,'facts':facts,'rawEvidence':raw,'scope':'expanded_retained_and_raw' if raw else 'expanded_retained_only'}
    sha=hashlib.sha256(json.dumps(revision,sort_keys=True,ensure_ascii=False).encode()).hexdigest();revision['sha256']=sha
    versions=folder/'retrieval-revisions';versions.mkdir(exist_ok=True)
    if not (versions/(sha+'.json')).exists():write_json(versions/(sha+'.json'),revision)
    write_json(folder/'retrieval.json',revision)
    return {'questionId':question_id,'retrievalSHA256':sha,'matches':len(facts),'rawMatches':sum(r['totalMatches'] for r in raw)}
