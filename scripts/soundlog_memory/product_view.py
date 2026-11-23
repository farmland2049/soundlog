"""Reviewed, result-first presentation. Diagnostic evidence stays in the workbench."""
import hashlib
import json
import re
from pathlib import Path
from .library_tools import library
from .store import write_json
from . import daily_archive, personal_items, workbench_view


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _fact_digest(fact):
    # Keep evidence hashes independent of the delivery folder.
    return _digest({key: value for key, value in fact.items() if key not in {'bundle', 'deliveryBundle'}})


def delivery_days(delivery):
    path = delivery/'catalog.json'
    return json.loads(path.read_text())['days'] if path.exists() else {}


def _reviewed_day(delivery, date, bundle):
    if not (delivery/bundle/'receipt.json').is_file():
        raise ValueError(f'{date} 缺少日交付回执')
    review = workbench_view.artifact(delivery, f'{bundle}/{date}/daily-review.json')
    return review.get('date') == date and review.get('mode') == 'agent_overview' and bool((review.get('overview') or '').strip())


def publish(root, spec):
    root = Path(root); delivery = root/'产出/自动交付'
    facts = {f['id']: f for f in library(delivery)}
    if spec.get('schemaVersion') != 1 or not spec.get('reviewer'):
        raise ValueError('成果方案须有版本与审阅者')
    seen = set(); bindings = {}; covered_days = {}
    catalog = delivery_days(delivery)
    for item in spec.get('activities', []):
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', item['id']) or item['id'] in seen:
            raise ValueError('活动编号无效或重复')
        seen.add(item['id'])
        if item['kind'] not in {'meeting', 'conversation', 'event'}:
            raise ValueError('活动类型无效')
        ids = item.get('factIds', [])
        if not ids or any(fid not in facts or facts[fid]['date'] != item['date'] for fid in ids):
            raise ValueError('活动须引用当日已交付内容')
        covered_days[item['date']] = catalog[item['date']]
        if not item.get('title') or not item.get('summary'):
            raise ValueError('活动标题与总结不能为空')
        for section in ('minutes', 'decisions', 'actions', 'openItems'):
            for row in item.get(section, []):
                if not row.get('text') or not row.get('factIds') or not set(row['factIds']) <= set(ids):
                    raise ValueError('成果段落必须有活动范围内的依据')
                if section == 'actions' and any('actions' not in facts[fid]['selectedCategories'] for fid in row['factIds']):
                    raise ValueError('待办不能从非事项材料生成')
        for fid in ids: bindings[fid] = _fact_digest(facts[fid])
    # A reviewed day with no retained facts can be delivered without an activity.
    fact_days = {fact['date'] for fact in facts.values()}
    for date, bundle in catalog.items():
        if date not in fact_days and _reviewed_day(delivery, date, bundle):
            covered_days[date] = bundle
    document = {'spec': spec, 'bindings': bindings, 'deliveryDays': covered_days}
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
    folder = pipeline.delivery/'product-views'/identifier
    if not (folder/'receipt.json').is_file():
        raise ValueError('成果页缺少发布回执')
    return workbench_view.artifact(pipeline.delivery, 'product-views/'+identifier+'/view.json')


def missing_delivery_days(pipeline, expected):
    document = _latest_view(pipeline)
    covered = document.get('deliveryDays', {}) if document else {}
    return {date: bundle for date, bundle in expected.items()
            if covered.get(date) != bundle or not _reviewed_day(pipeline.delivery, date, bundle)}


def publish_reviewed_scenes(pipeline, missing):
    """Fill missing dates from reviewed scenes while preserving existing activities."""
    document = _latest_view(pipeline)
    spec = document['spec'] if document else {'schemaVersion': 1, 'reviewer': '复用已审阅的每日复盘场景'}
    activities = list(spec.get('activities', []))
    activity_days = {item['date'] for item in activities}
    existing_ids = {item['id'] for item in activities}
    for date, bundle in sorted(missing.items()):
        base = f'{bundle}/{date}'
        if not _reviewed_day(pipeline.delivery, date, bundle):
            raise ValueError(f'{date} 缺少已审阅的每日复盘')
        if date in activity_days:
            if document is not None and 'deliveryDays' not in document:
                # Legacy bindings have already been verified against the active bundle.
                continue
            raise ValueError(f'{date} 的交付包已更新，请重新发布该日成果页')
        scenes = workbench_view.artifact(pipeline.delivery, f'{base}/scenes.json')
        if scenes['contentCards'] and not scenes['reviewedScenes']:
            raise ValueError(f'{date} 缺少可补发的审阅场景')
        for scene in scenes['reviewedScenes']:
            identifier = scene['id']
            if identifier in existing_ids:
                raise ValueError(f'{date} 的场景编号与已有成果重复')
            existing_ids.add(identifier)
            activities.append({
                'id': identifier, 'kind': 'event', 'date': date,
                'title': scene['title'], 'summary': scene['summary'], 'factIds': scene['factIds'],
                'minutes': [{'text': section['text'], 'factIds': section['factIds']}
                            for section in scene.get('sections', [])],
            })
    return publish(pipeline.root, {**spec, 'activities': activities})


def _activities(pipeline, facts):
    document = _latest_view(pipeline)
    if document is None: return []
    for fid, binding in document['bindings'].items():
        if fid not in facts:
            raise ValueError('成果依据已有更新，请重新整理后查看')
        digest = _fact_digest(facts[fid]) if 'deliveryDays' in document else _digest(facts[fid])
        if digest != binding:
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


def _followups(delivery, facts):
    path = delivery/'task-graph.json'
    if not path.exists():
        return []
    graph = json.loads(path.read_text())
    mentioned = {entry['factId']: entry for task in graph['tasks'] for entry in task['timeline']
                 if entry['factId'] in facts and entry['bundle'] == facts[entry['factId']]['bundle']}
    labels = {'same_task': '审阅为同一事项', 'possible_same_task': '可能相关', 'contradicts': '说法有冲突'}
    followups = []
    revoked = {link.get('target') for link in graph['links'] if link['relation'] == 'revoke'}
    for link in graph['links']:
        if link['relation'] not in labels or link['id'] in revoked:
            continue
        entries = [mentioned.get(link[k]) for k in ('from', 'to')]
        if not all(entries):
            continue
        timeline = sorted(entries, key=lambda entry: entry['recordedStart'])
        followups.append({'label': labels[link['relation']], 'reason': link['reason'],
                          'timeline': [{key: entry[key] for key in ('date', 'summary')} for entry in timeline]})
    return sorted(followups, key=lambda item: item['timeline'][-1]['date'], reverse=True)


def results(pipeline):
    catalog_path = pipeline.delivery/'catalog.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {'days':{}}
    facts = {f['id']:f for f in library(pipeline.delivery)} if catalog['days'] else {}
    activities = _activities(pipeline, facts)
    curated = {a['date'] for a in activities}
    days = []
    archives = daily_archive.statuses(pipeline, catalog['days'])
    meeting_dates = {fact['date'] for fact in facts.values() if 'minutes' in fact.get('selectedCategories', [])}
    for date, bundle in sorted(catalog['days'].items(), reverse=True):
        review = workbench_view.artifact(pipeline.delivery, bundle+'/'+date+'/daily-review.json')
        days.append({'date':date, 'summary':review.get('overview') or '', 'archive':archives[date],
                     'reviewDocument':f'{bundle}/{date}/daily-review.md',
                     'minutes':f'{bundle}/{date}/minutes.md' if date in meeting_dates else None})
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
    try:
        personal = [{'kind':item['kind'], 'summary':item['summary'], 'date':item['recordedStart'][:10]}
                    for item in personal_items.view(pipeline.root)['items']]
    except (OSError, ValueError, KeyError, TypeError):
        personal = []
    return {'days':days, 'activities':sorted(activities, key=lambda a:(a['date'],a['time']), reverse=True),
            'knowledge':knowledge, 'writing':writing, 'reviews':reviews, 'personal':personal,
            'followups':_followups(pipeline.delivery,facts)}
