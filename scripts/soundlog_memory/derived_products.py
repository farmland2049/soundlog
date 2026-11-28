"""Publish evidence-linked knowledge, visual, clean-text and writing artifacts."""
import difflib
import hashlib
import html
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from .library_tools import library
from .scenes import digest_bytes
from .store import write_json


def _text(x):
    if not isinstance(x,str) or not x.strip(): raise ValueError('文本不能为空')
    return x


def _id(x):
    if not isinstance(x,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',x):raise ValueError('派生产物编号无效')
    return x


def publish_derived(delivery, spec, raw_snapshot=None):
    delivery=Path(delivery);facts={f['id']:f for f in library(delivery)}
    if spec.get('schemaVersion')!=1 or not spec.get('reviewer'):raise ValueError('派生方案版本或审阅者缺失')
    def refs(ids):
        if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids) or any(k not in facts for k in ids):raise ValueError('派生产物引用无效')
        return [facts[k] for k in ids]
    def links(ids, prefix='../../'):
        return [f"- [原文]({prefix}{f['bundle']}/{f['date']}/sources.md#{e['id']}) · {e['start']} · `{e['sourceFile']}`" for f in refs(ids) for e in f['evidence']]
    topics=spec.get('topics',[]);topic_ids=set()
    for t in topics:
        if _id(t['id']) in topic_ids:raise ValueError('知识主题重复')
        topic_ids.add(t['id']);_text(t['title'])
        if t['audience'] not in {'child','adult'}:raise ValueError('学习受众必须区分儿童和成人')
        fs=refs(t['factIds'])
        if t['audience']=='child' and any('child_learning' not in f.get('selectedCategories',[]) for f in fs):raise ValueError('儿童主题引用了未分类为儿童学习的内容')
        if t['audience']=='adult' and any('child_learning' in f.get('selectedCategories',[]) for f in fs):raise ValueError('儿童学习不能混入成人主题')
        for key in ('concepts','methods','examples','questions'):
            for part in t.get(key,[]):
                _text(part['text']);refs(part['factIds'])
                if not set(part['factIds'])<=set(t['factIds']):raise ValueError('知识字段越出主题引用范围')
        for thought in t.get('sprouts',[]):_text(thought)
    for rel in spec.get('topicRelations',[]):
        if rel.get('from') not in topic_ids or rel.get('to') not in topic_ids or rel['from']==rel['to']:raise ValueError('主题关联节点无效')
        if rel.get('type') not in {'shared_theme','supplements','contradicts','question'}:raise ValueError('主题关系无效，不自动推断因果')
        _text(rel['reason']);refs(rel['factIds'])
    evidence={e['id']:e for f in facts.values() for e in f['evidence']}
    raw_identities = []
    snapshots = raw_snapshot if isinstance(raw_snapshot, list) else [raw_snapshot] if raw_snapshot else []
    for snapshot_path in snapshots:
        from .scenes import resolve_snapshot
        snapshot=resolve_snapshot(snapshot_path);raw_receipt=json.loads((snapshot/'receipt.json').read_text())
        raw_identities.append(raw_receipt['snapshotId'])
        for name,sha in raw_receipt['artifacts'].items():
            if name.endswith('_utterances.json'):
                path=snapshot/name
                if digest_bytes(path)!=sha:raise ValueError('派生原文快照已改变')
                evidence.update({e['id']:e for e in json.loads(path.read_text())['utterances']})
    clean_ids=set()
    for c in spec.get('cleanDocuments',[]):
        if _id(c['id']) in clean_ids:raise ValueError('规整稿编号重复')
        clean_ids.add(c['id'])
        for p in c['paragraphs']:
            e=evidence.get(p['evidenceId'])
            if not e or p['sourceText']!=e['text']:raise ValueError('规整稿必须绑定完整原句')
            clean=_text(p['cleanText'])
            # These guards catch destructive rewrites; agent still checks sentence meaning.
            for token in ('不','没','未','如果','可能','再','才','就','要','只要','除非','明天','后天','今天'):
                if token in p['sourceText'] and token not in clean:raise ValueError('规整稿丢失否定、条件或不确定表达')
            if re.findall(r'\d+(?:\.\d+)?',p['sourceText'])!=re.findall(r'\d+(?:\.\d+)?',clean):raise ValueError('规整稿改变数字')
            _text(p['reason'])
    for mark in spec.get('marks',[]):
        if mark.get('evidenceId') not in evidence or mark.get('classification') not in {'mark','quoted','not_instruction','unknown'}:raise ValueError('MARK依据或性质无效')
        _text(mark['reason'])
    for draft in spec.get('intents',[]):
        _id(draft['id']);refs(draft['factIds']);_text(draft['request'])
        if draft.get('state')!='draft':raise ValueError('语音请求只能生成草稿，不从历史录音直接执行')
    for plan in spec.get('writingPlans',[]):
        _id(plan['id']);_text(plan['title']);refs(plan['factIds'])
        if plan.get('format') not in {'article','report','speech'}:raise ValueError('写作类型无效')
        for section in plan['sections']:
            _text(section['title']);refs(section['factIds'])
            if not set(section['factIds'])<=set(plan['factIds']):raise ValueError('写作引用越界')
    identity=hashlib.sha256(json.dumps({'spec':spec,'facts':facts,'rawSnapshotId':raw_identities[0] if len(raw_identities) == 1 else raw_identities or None,'implementation':digest_bytes(Path(__file__))},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    parent=delivery/'derived';parent.mkdir(exist_ok=True);final=parent/('derived-'+identity)
    stage=Path(tempfile.mkdtemp(prefix='.building-',dir=parent))
    try:
        write_json(stage/'spec.json',spec)
        (stage/'knowledge').mkdir();(stage/'clean').mkdir();(stage/'writing').mkdir()
        mmd=['flowchart TD']; cards=[];index=['# 知识、重点与创作入口','','[主题图与信息卡](index.html) · [重点标记](highlights.md) · [请求草稿](intent-drafts.json)','','## 知识卡','']
        for t in topics:
            lines=['# '+t['title'],'','受众：'+('儿童学习' if t['audience']=='child' else '成人学习/讨论'),'','以下为录音材料整理，观点正确性另行核实；外部来源与本人观点不自动互换。','']
            for key,label in [('concepts','概念与观点'),('methods','方法'),('examples','例子'),('questions','录音中的疑问')]:
                lines+=['## '+label,'']
                for p in t.get(key,[]):lines += [p['text'],'']+links(p['factIds'],'../../../')+['']
            lines+=['## Agent新增联想','','以下问题由agent新增，不是录音原话或历史事实。','']+['- '+x for x in t.get('sprouts',[])]
            (stage/'knowledge'/(t['id']+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
            write_json(stage/'knowledge'/(t['id']+'.json'),t)
            mmd.append('  '+t['id'].replace('-','_')+'['+json.dumps(t['title'],ensure_ascii=False)+']')
            index += [f"- [{t['title']}](knowledge/{t['id']}.md)"]
            cards.append('<article id="'+t['id']+'"><h2>'+html.escape(t['title'])+'</h2><p>'+('儿童学习' if t['audience']=='child' else '成人学习')+'</p>'+''.join('<h3>'+label+'</h3>'+''.join('<p>'+html.escape(p['text'])+'</p>' for p in t.get(key,[])) for key,label in [('concepts','概念'),('methods','方法'),('examples','例子'),('questions','问题')])+'<a href="knowledge/'+t['id']+'.md">完整卡片及原文</a><details><summary>Agent新增联想</summary>'+''.join('<p>'+html.escape(x)+'</p>' for x in t.get('sprouts',[]))+'</details></article>')
        for rel in spec.get('topicRelations',[]):mmd.append('  '+rel['from'].replace('-','_')+' -->|'+rel['type']+'| '+rel['to'].replace('-','_'))
        (stage/'mindmap.mmd').write_text('\n'.join(mmd)+'\n')
        (stage/'mindmap.md').write_text('# 主题关系图\n\n边是审阅过的主题关系，不代表因果。\n\n```mermaid\n'+'\n'.join(mmd)+'\n```\n')
        relation_html=''.join('<li><a href="#'+r['from']+'">'+html.escape(r['from'])+'</a> → <a href="#'+r['to']+'">'+html.escape(r['to'])+'</a>：'+html.escape(r['reason'])+'</li>' for r in spec.get('topicRelations',[]))
        positions={};counts={'adult':0,'child':0}
        for topic in topics:
            audience=topic['audience'];positions[topic['id']]=(30 if audience=='adult' else 480,90+120*counts[audience]);counts[audience]+=1
        height=180+120*max(counts.values(),default=0)
        svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 '+str(height)+'" role="img" aria-label="有原文依据的主题关系图">','<rect width="940" height="'+str(height)+'" fill="#f4f7f1"/>','<text x="30" y="35" font-size="21">成人学习</text><text x="480" y="35" font-size="21">儿童学习</text>']
        for relation in spec.get('topicRelations',[]):
            x1,y1=positions[relation['from']];x2,y2=positions[relation['to']]
            svg.append('<path d="M '+str(x1+390)+' '+str(y1+35)+' C '+str(x1+430)+' '+str(y1+35)+', '+str(x2+430)+' '+str(y2+35)+', '+str(x2+390)+' '+str(y2+35)+'" fill="none" stroke="#66846d" stroke-width="2"><title>'+html.escape(relation['type']+'：'+relation['reason'])+'</title></path>')
        for topic in topics:
            x,y=positions[topic['id']]
            svg.append('<a href="#'+topic['id']+'"><rect x="'+str(x)+'" y="'+str(y)+'" width="390" height="70" rx="12" fill="white" stroke="#55755c"/><text x="'+str(x+15)+'" y="'+str(y+40)+'" font-size="18">'+html.escape(topic['title'][:20])+'</text><title>'+html.escape(topic['title'])+'</title></a>')
        svg.append('</svg>');svg=''.join(svg)
        (stage/'mindmap.svg').write_text(svg,encoding='utf-8')
        (stage/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>主题与信息卡</title><style>body{font:17px/1.65 system-ui;max-width:960px;margin:36px auto;padding:16px;background:#f6f5ef}article{background:white;padding:24px;margin:20px 0;border-radius:12px}h3{font-size:1em}</style><h1>知识与主题关系</h1><p>保留原文来源；新增思考单独标记。</p>'+svg+'<ul>'+relation_html+'</ul>'+''.join(cards),encoding='utf-8')
        corrections=[]
        for c in spec.get('cleanDocuments',[]):
            lines=['# '+c.get('title',c['id']),'','独立规整建议；原始机器转写保持不变。','']
            for p in c['paragraphs']:
                e=evidence[p['evidenceId']];lines+=['## '+e['start'],'',f"来源：`{e['sourceFile']}` · {e['startOffsetSeconds']}—{e['endOffsetSeconds']}秒 · `{e['id']}`",'','### 原文','',p['sourceText'],'','### 规整稿','',p['cleanText'],'','理由：'+p['reason'],'']
                diff=''.join(difflib.unified_diff(p['sourceText'].splitlines(True),p['cleanText'].splitlines(True),fromfile='原文',tofile='规整稿'))
                corrections.append({**p,'documentId':c['id'],'diff':diff,'status':'suggested'})
            (stage/'clean'/(c['id']+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
        write_json(stage/'corrections.json',corrections)
        highlights=['# 重点标记','','口令识别是历史内容整理，不是当前执行授权。','']
        for mark in spec.get('marks',[]):
            e=evidence[mark['evidenceId']];highlights+=['## '+e['start']+'｜'+mark['classification'],'',mark['reason'],'',f"来源：`{e['sourceFile']}` · {e['startOffsetSeconds']}—{e['endOffsetSeconds']}秒 · `{e['id']}`",'','> '+e['text'],'']
        (stage/'highlights.md').write_text('\n'.join(highlights)+'\n',encoding='utf-8');write_json(stage/'intent-drafts.json',spec.get('intents',[]))
        index+=['','## 规整稿','']+[f"- [{c.get('title',c['id'])}](clean/{c['id']}.md)" for c in spec.get('cleanDocuments',[])]
        index+=['','## 写作素材','']
        for plan in spec.get('writingPlans',[]):
            lines=['# '+plan['title'],'','用途：'+plan['format']+'；下列结构为agent组织建议，不表示录音中已形成这篇文章。','']
            for section in plan['sections']:
                lines+=['## '+section['title'],'']
                for f in refs(section['factIds']):lines += [f['summary'],'']
                lines+=links(section['factIds'],'../../../')+['']
            (stage/'writing'/(plan['id']+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8');index += [f"- [{plan['title']}](writing/{plan['id']}.md)"]
        (stage/'README.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
        artifacts={str(p.relative_to(stage)):digest_bytes(p) for p in stage.rglob('*') if p.is_file()}
        receipt={'id':final.name,'state':'completed','topics':len(topics),'cleanDocuments':len(clean_ids),'writingPlans':len(spec.get('writingPlans',[])),'artifacts':artifacts}
        write_json(stage/'receipt.json',receipt)
        if final.exists():
            if json.loads((final/'receipt.json').read_text())!=receipt or any(digest_bytes(final/n)!=h for n,h in artifacts.items()):raise ValueError('已有派生版本已改变')
            shutil.rmtree(stage)
        else:os.rename(stage,final)
        write_json(parent/'latest.json',receipt)
        return receipt
    finally:
        if stage.exists():shutil.rmtree(stage)
