"""Reviewed, result-first presentation. Diagnostic evidence stays in the workbench."""
import hashlib
import json
import re
from pathlib import Path
from .library_tools import library
from .store import write_json
from . import workbench_view


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _fact_digest(fact):
    # A fact's delivery bundle is a mutable storage pointer, not reviewed content.
    return _digest({key:value for key,value in fact.items() if key!='deliveryBundle'})


def publish(root, spec):
    root = Path(root); delivery = root/'产出/自动交付'
    facts = {f['id']: f for f in library(delivery)}
    if spec.get('schemaVersion') != 1 or not spec.get('reviewer'):
        raise ValueError('成果方案须有版本与审阅者')
    seen = set(); bindings = {}
    for item in spec.get('activities', []):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', item['id']) or item['id'] in seen:
            raise ValueError('活动编号无效或重复')
        seen.add(item['id'])
        if item['kind'] not in {'meeting', 'conversation', 'event'}:
            raise ValueError('活动类型无效')
        ids = item.get('factIds', [])
        if not ids or any(fid not in facts or facts[fid]['date'] != item['date'] for fid in ids):
            raise ValueError('活动须引用当日已交付内容')
        if not item.get('title') or not item.get('summary'):
            raise ValueError('活动标题与总结不能为空')
        for section in ('minutes', 'decisions', 'actions', 'openItems'):
            for row in item.get(section, []):
                if not row.get('text') or not row.get('factIds') or not set(row['factIds']) <= set(ids):
                    raise ValueError('成果段落必须有活动范围内的依据')
                if section == 'actions' and any('actions' not in facts[fid]['selectedCategories'] for fid in row['factIds']):
                    raise ValueError('待办不能从非事项材料生成')
        for fid in ids: bindings[fid] = _fact_digest(facts[fid])
    document = {'spec': spec, 'bindings': bindings}
    identifier = 'product-view-' + _digest(document)[:24]
    home = delivery/'product-views'; folder = home/identifier
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'view.json'
    if path.exists() and json.loads(path.read_text()) != document:
        raise ValueError('已有成果版本冲突')
    write_json(path, document)
    write_json(folder/'receipt.json', {'state':'completed', 'artifacts':{'view.json': hashlib.sha256(path.read_bytes()).hexdigest()}})
    write_json(home/'latest.json', {'id':identifier})
    return {'id':identifier, 'activities':len(spec['activities'])}


def _latest_view(pipeline):
    path = pipeline.delivery/'product-views/latest.json'
    if not path.exists(): return None
    identifier = json.loads(path.read_text())['id']
    if not re.fullmatch(r'product-view-[a-f0-9]{24}', identifier): raise ValueError('成果路径无效')
    return workbench_view.artifact(pipeline.delivery, 'product-views/'+identifier+'/view.json')


def publish_reviewed_scenes(pipeline, bundle):
    """Publish already reviewed scenes when a new day has no product view yet."""
    document = _latest_view(pipeline)
    spec = document['spec'] if document else {'schemaVersion': 1, 'reviewer': '复用已审阅的每日复盘场景'}
    activities = list(spec.get('activities', []))
    catalog = json.loads((pipeline.delivery/'catalog.json').read_text())['days']
    days = sorted(date for date, current in catalog.items() if current == bundle)
    if not days or any(item['date'] in days for item in activities):
        return None
    existing_ids = {item['id'] for item in activities}
    for date in days:
        base = f'{bundle}/{date}'
        review = workbench_view.artifact(pipeline.delivery, f'{base}/daily-review.json')
        scenes = workbench_view.artifact(pipeline.delivery, f'{base}/scenes.json')
        if review.get('mode') != 'agent_overview' or not (review.get('overview') or '').strip():
            return None
        if scenes['contentCards'] and not scenes['reviewedScenes']:
            return None
        for scene in scenes['reviewedScenes']:
            identifier = scene['id']
            if identifier in existing_ids:
                return None
            existing_ids.add(identifier)
            activities.append({
                'id': identifier, 'kind': 'event', 'date': date,
                'title': scene['title'], 'summary': scene['summary'], 'factIds': scene['factIds'],
                'minutes': [{'text': section['text'], 'factIds': section['factIds']}
                            for section in scene.get('sections', [])],
            })
    return publish(pipeline.root, {**spec, 'activities': activities, 'reviewedSceneBundle': bundle})


def _activities(pipeline, facts):
    document = _latest_view(pipeline)
    if document is None: return []
    for fid, binding in document['bindings'].items():
        if fid not in facts or _fact_digest(facts[fid]) != binding:
            raise ValueError('成果依据已有更新，请重新整理后查看')
    # Explicit allowlist: no transcript, offsets, source files, internal IDs or hashes.
    output = []
    for item in document['spec']['activities']:
        fs = [facts[fid] for fid in item['factIds']]
        start = min(f['recordedStart'] for f in fs)[11:16]
        end = max(f['recordedEnd'] for f in fs)[11:16]
        clean = {k:item[k] for k in ('kind','title','summary','date')}
        clean['time'] = start + '—' + end
        for section in ('minutes','decisions','actions','openItems'):
            clean[section] = [{k:row[k] for k in ('text','owner','due') if row.get(k)} for row in item.get(section, [])]
        output.append(clean)
    return output


def results(pipeline):
    catalog_path = pipeline.delivery/'catalog.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {'days':{}}
    facts = {f['id']:f for f in library(pipeline.delivery)} if catalog['days'] else {}
    activities = _activities(pipeline, facts)
    curated = {a['date'] for a in activities}
    days = []
    for date, bundle in sorted(catalog['days'].items(), reverse=True):
        review = workbench_view.artifact(pipeline.delivery, bundle+'/'+date+'/daily-review.json')
        days.append({'date':date, 'summary':review.get('overview') or ''})
        if date in curated: continue
        scenes = workbench_view.artifact(pipeline.delivery, bundle+'/'+date+'/scenes.json')['reviewedScenes']
        for scene in scenes:
            fs = [facts[fid] for fid in scene['factIds'] if fid in facts]
            if not fs: continue
            activities.append({'kind':'event', 'date':date, 'title':scene['title'], 'summary':scene['summary'],
                'time':min(f['recordedStart'] for f in fs)[11:16]+'—'+max(f['recordedEnd'] for f in fs)[11:16],
                'minutes':[{'text':s['text']} for s in scene.get('sections', [])], 'actions':[], 'decisions':[], 'openItems':[]})
    derived = workbench_view.derived(pipeline.delivery)
    knowledge = [{k:t[k] for k in ('title','audience','concepts','methods','examples','questions','sprouts') if k in t} for t in derived['topics']]
    for topic in knowledge:
        for key in ('concepts','methods','examples','questions'):
            topic[key] = [x['text'] for x in topic.get(key, [])]
    writing = [{'title':p['title'], 'sections':[{'title':s['title'], 'texts':[facts[fid]['summary'] for fid in s['factIds'] if fid in facts]} for s in p['sections']]} for p in derived['writingPlans']]
    reviews = [{'start':r['start'], 'end':r['end'], 'missingDays':r['missingDays'],
                'updated':not r['needsRefresh'], 'sections':[{'title':s['title'],'text':s['text']} for s in r['sections']]} for r in workbench_view.reviews(pipeline.delivery)] if catalog['days'] else []
    return {'days':days, 'activities':sorted(activities, key=lambda a:(a['date'],a['time']), reverse=True), 'knowledge':knowledge, 'writing':writing, 'reviews':reviews}
