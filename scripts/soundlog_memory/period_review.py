"""Versioned cross-day reviews grounded in published daily evidence."""
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from .library_tools import library
from .scenes import digest_bytes
from .store import write_json, atomic


def period_material(delivery, start, end):
    delivery = Path(delivery)
    begin, finish = date.fromisoformat(start), date.fromisoformat(end)
    if begin.isoformat()!=start or finish.isoformat()!=end or not 0 <= (finish-begin).days <= 365:
        raise ValueError('日期范围须为有效ISO日期、顺序正确且不超过366天')
    catalog = json.loads((delivery/'catalog.json').read_text())
    requested = [(begin+timedelta(days=i)).isoformat() for i in range((finish-begin).days+1)]
    available = [d for d in requested if d in catalog['days']]
    days=[]; bindings={}
    for day in available:
        bundle=catalog['days'][day]
        if Path(bundle).name!=bundle or not bundle.startswith('bundle-'):raise ValueError('日交付路径越界')
        folder=delivery/bundle
        receipt=json.loads((folder/'receipt.json').read_text())
        if receipt.get('state')!='completed':raise ValueError('日交付尚未完成')
        names=['search.json',day+'/daily-review.json',day+'/scenes.json']
        for name in names:
            if digest_bytes(folder/name)!=receipt['artifacts'].get(name):raise ValueError('复盘来源已改变')
            bindings[bundle+'/'+name]=receipt['artifacts'][name]
        daily=json.loads((folder/day/'daily-review.json').read_text())
        scenes=json.loads((folder/day/'scenes.json').read_text())
        days.append({'date':day,'bundle':bundle,'overview':daily.get('overview'),
                     'highlights':daily.get('highlights',[]),'scenes':scenes.get('reviewedScenes',[])})
    facts=[f for f in library(delivery) if start<=f['date']<=end]
    return {'schemaVersion':1,'start':start,'end':end,'days':days,'facts':facts,
            'missingDays':[d for d in requested if d not in available], 'bindings':bindings,
            'categoryCounts':dict(Counter(c for f in facts for c in f['selectedCategories'])),
            'boundary':'没有交付的日期表示资料缺口，不代表没有活动；事项性质为历史录音状态。'}


def publish_period_review(delivery, start, end, spec=None):
    delivery=Path(delivery);material=period_material(delivery,start,end)
    if not material['days']:raise ValueError('范围内没有已交付日期，不生成空复盘')
    facts={f['id']:f for f in material['facts']}
    if spec is not None:
        if spec.get('start')!=start or spec.get('end')!=end or not isinstance(spec.get('reviewer'),str) or not spec['reviewer'].strip():
            raise ValueError('复盘范围或审阅者无效')
        if not isinstance(spec.get('sections'),list) or not spec['sections']:raise ValueError('复盘须有带依据的段落')
        for section in spec['sections']:
            ids=section.get('factIds')
            if not section.get('title') or not isinstance(section.get('text'),str) or not section['text'].strip():raise ValueError('复盘段落内容为空')
            if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids) or any(i not in facts for i in ids):raise ValueError('复盘依据须为范围内保留项')
            category=section.get('category')
            if category not in {'work','life','actions','child_learning','adult_learning'}:raise ValueError('复盘栏目无效')
            for fid in ids:
                selected=facts[fid]['selectedCategories']
                if category in {'child_learning','adult_learning'} and category not in selected:raise ValueError('学习复盘受众不匹配')
                if category=='adult_learning' and 'child_learning' in selected:raise ValueError('儿童材料不能混为成人学习')
                if category=='actions' and 'actions' not in selected:raise ValueError('历史事项引用非事项材料')
    identity={'material':material,'spec':spec,'implementation':digest_bytes(Path(__file__))}
    sha=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    parent=delivery/'reviews';parent.mkdir(exist_ok=True);target=parent/('review-'+sha[:24])
    stage=Path(tempfile.mkdtemp(prefix='.building-',dir=parent))
    try:
        write_json(stage/'material.json',material)
        write_json(stage/'review.json',{'start':start,'end':end,'mode':'agent_review' if spec is not None else 'evidence_index','reviewer':spec.get('reviewer') if spec else None,'sections':spec['sections'] if spec else []})
        lines=[f'# {start}—{end} 跨天复盘','','此页依据已交付录音整理，不能代表完整生活或当前事项状态。', '',
               f"已交付日期：{len(material['days'])}；保留内容：{len(facts)}（多用途可重复计栏目）。",'',
               '缺少交付资料的日期：'+('、'.join(material['missingDays']) or '无')+'。缺失不等于没有活动。','']
        if spec:
            lines+=['处理者：'+spec['reviewer']+'；此为agent整理，独立语义验收另计。','']
            for section in spec['sections']:
                lines+=['## '+section['title'],'',section['text'],'']
                for fid in section['factIds']:
                    f=facts[fid]
                    lines+=[f"- [对应内容]({ '../../'+f['bundle']+'/'+f['date']+'/scenes/'+fid+'.md'}) · {f['date']}"]
                    for e in f['evidence']:
                        lines+=[f"- [原文](../../{f['bundle']}/{f['date']}/sources.md#{e['id']}) · {e['start']} · `{e['sourceFile']}` · {e['startOffsetSeconds']}秒",'> '+e['quote'],'']
        else:lines+=['## 待整理','','当前仅是证据索引，尚未由agent生成跨天结论。','']
        lines+=['## 逐日回查','']
        for day in material['days']:
            lines+=[f"### [{day['date']}](../../{day['bundle']}/{day['date']}/README.md)",'',day['overview'] or '尚无单独日复盘。','']
        (stage/'README.md').write_text('\n'.join(lines)+'\n')
        receipt={'id':target.name,'start':start,'end':end,'mode':'agent_review' if spec else 'evidence_index','state':'completed','inputSHA256':sha,
                 'artifacts':{p.name:digest_bytes(p) for p in stage.iterdir() if p.is_file()}}
        write_json(stage/'receipt.json',receipt)
        if target.exists():
            if json.loads((target/'receipt.json').read_text())!=receipt:raise ValueError('既有复盘版本冲突')
            for name,expected in receipt['artifacts'].items():
                if digest_bytes(target/name)!=expected:raise ValueError('既有复盘工件已改变')
            shutil.rmtree(stage)
        else:os.replace(stage,target)
        catalog_path=parent/'catalog.json'
        catalog=json.loads(catalog_path.read_text()) if catalog_path.exists() else {'periods':{}}
        key=start+'_'+end
        # An index refresh must not silently replace a reviewed narrative.
        prior=catalog['periods'].get(key)
        if prior and spec is None:
            if Path(prior).name!=prior or not prior.startswith('review-'):raise ValueError('复盘目录越界')
            old=json.loads((parent/prior/'receipt.json').read_text())
            if old['mode']=='agent_review':
                original=json.loads((parent/prior/'material.json').read_text())
                return {**receipt,'selected':prior,'selection':'kept_reviewed_version',
                        'reviewNeedsRefresh':original['bindings']!=material['bindings']}
        catalog['periods'][key]=target.name
        write_json(catalog_path,catalog)
        atomic(parent/'README.md','# 跨天复盘\n\n'+ '\n'.join(f'- [{period.replace("_","—")}]({rid}/README.md)' for period,rid in sorted(catalog['periods'].items()))+'\n')
        return {**receipt,'selected':target.name}
    finally:
        if stage.exists():shutil.rmtree(stage)
