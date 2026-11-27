"""Read verified product artifacts into a UI projection; never infer new facts."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from .library_tools import library
from .scenes import digest_bytes


def artifact(delivery, relative):
    delivery=Path(delivery).resolve();path=(delivery/relative).resolve()
    if not path.is_relative_to(delivery) or not path.is_file():raise ValueError('产物不存在或越界')
    parent=path.parent
    while parent!=delivery:
        receipt=parent/'receipt.json'
        if receipt.exists():
            meta=json.loads(receipt.read_text());name=str(path.relative_to(parent))
            if meta.get('state')!='completed' or meta.get('artifacts',{}).get(name)!=digest_bytes(path):raise ValueError('产物校验失败')
            break
        parent=parent.parent
    return json.loads(path.read_text()) if path.suffix=='.json' else path.read_text()


def derived(delivery):
    path=Path(delivery)/'derived/latest.json'
    if not path.exists():return {'topics':[],'cleanDocuments':[],'marks':[],'intents':[],'writingPlans':[],'base':None}
    rid=json.loads(path.read_text())['id']
    if not re.fullmatch(r'derived-[a-f0-9]{24}',rid):raise ValueError('派生目录无效')
    base='derived/'+rid
    return {**artifact(delivery,base+'/spec.json'),'base':base}


def reviews(delivery):
    delivery=Path(delivery);path=delivery/'reviews/catalog.json'
    if not path.exists():return []
    current=json.loads((delivery/'catalog.json').read_text())['days'];rows=[]
    for period,rid in sorted(json.loads(path.read_text())['periods'].items(),reverse=True):
        if not re.fullmatch(r'review-[a-f0-9]{24}',rid):raise ValueError('复盘编号无效')
        base='reviews/'+rid;review=artifact(delivery,base+'/review.json');material=artifact(delivery,base+'/material.json')
        old={d['date']:d['bundle'] for d in material['days']}
        covered={day:bundle for day,bundle in current.items() if review['start']<=day<=review['end']}
        stale=old!=covered
        for name,sha in material['bindings'].items():
            if not stale and digest_bytes(delivery/name)!=sha:stale=True
        rows.append({**review,'id':rid,'path':base+'/README.md','days':material['days'],'missingDays':material['missingDays'],
                     'factCount':len(material['facts']),'needsRefresh':stale})
    return rows


def overview(pipeline):
    delivery=pipeline.delivery;catalog_path=delivery/'catalog.json'
    catalog=json.loads(catalog_path.read_text()) if catalog_path.exists() else {'days':{}}
    facts=library(delivery) if catalog['days'] else [];counts=Counter(f['date'] for f in facts);days=[]
    for day,bundle in sorted(catalog['days'].items(),reverse=True):
        daily=artifact(delivery,bundle+'/'+day+'/daily-review.json')
        categories=Counter(c for f in facts if f['date']==day for c in f['selectedCategories'])
        days.append({'date':day,'count':counts[day],'overview':daily.get('overview'),'categories':dict(categories),'bundle':bundle})
    graph_path=delivery/'task-graph.json';graph=json.loads(graph_path.read_text()) if graph_path.exists() else {'tasks':[]}
    d=derived(delivery) if catalog['days'] else {'topics':[],'writingPlans':[],'cleanDocuments':[],'marks':[],'intents':[]}
    state=pipeline.audio_state();manual_path=pipeline.home/'manual-run.json'
    manual=json.loads(manual_path.read_text()) if manual_path.exists() else None
    stages=[('audio','转写、环境声分类、说话人分离与原文对齐'),('archive','按天归档')]
    phase=state['state']
    active={'processing_audio':0,'archiving_audio':1}.get(phase)
    ready=[bool(state.get('archiveIndex'))]*2
    return {'days':days,'totals':{'days':len(days),'facts':len(facts),'tasks':len(graph['tasks']),'topics':len(d['topics']),'writing':len(d['writingPlans'])},
            'categories':dict(Counter(c for f in facts for c in f['selectedCategories'])),
            'pipeline':{'state':phase,'stages':[{'id':key,'title':title,'status':'active' if i==active else ('available' if ready[i] else 'empty')} for i,(key,title) in enumerate(stages)],'inbox':[{'name':p.name,'bytes':p.stat().st_size} for p in pipeline.inventory()],'manual':manual},
            'derivedCounts':{k:len(d.get(k,[])) for k in ('topics','writingPlans','cleanDocuments','marks','intents')},
            'rootKey':hashlib.sha256(str(pipeline.root.resolve()).encode()).hexdigest()[:24]}


def day_view(pipeline, day):
    if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError('日期无效')
    catalog=json.loads((pipeline.delivery/'catalog.json').read_text())
    bundle=catalog['days'].get(day)
    if not bundle:raise ValueError('该日尚无交付资料')
    facts=[f for f in library(pipeline.delivery) if f['date']==day]
    return {'date':day,'bundle':bundle,'facts':facts,'review':artifact(pipeline.delivery,bundle+'/'+day+'/daily-review.json'),
            'scenes':artifact(pipeline.delivery,bundle+'/'+day+'/scenes.json')['reviewedScenes']}


def connections(pipeline):
    from .voice_calibration import state as voice_state
    home=pipeline.root/'记忆库/运行/产品功能';actions=[]
    for folder in sorted((home/'actions').glob('action-*')):
        if not re.fullmatch(r'action-[a-f0-9]{24}',folder.name) or not (folder/'draft.json').exists():continue
        draft=json.loads((folder/'draft.json').read_text());receipt_path=folder/'receipt.json'
        receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
        action=draft['action']
        actions.append({'id':folder.name,'title':action['title'],'start':action['start'],'end':action['end'],
                        'state':receipt['state'] if receipt else 'draft','application':receipt.get('application','Calendar') if receipt else 'Calendar',
                        'mode':receipt.get('mode') if receipt else None,'hasReadback':bool(receipt and receipt.get('readback'))})
    identity=home/'identity-scopes.json'
    return {'actions':actions,'identityScopes':len(json.loads(identity.read_text())['bindings']) if identity.exists() else 0,
            'voiceCalibration':voice_state(pipeline.root)['counts'],
            'boundary':'显示本机已有操作记录；界面不会新增身份绑定、正式记忆写入或对外执行。'}
