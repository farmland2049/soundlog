"""Explicit self-voice calibration, kept separate from inferred identity."""
import hashlib
import json
from pathlib import Path
from .library_tools import library
from .store import write_json
from .audio_access import evidence


def home(root):return Path(root)/'记忆库/运行/本人声音'

def checksum(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def prepare(root,limit=10,persist=True):
    root=Path(root);folder=home(root);folder.mkdir(parents=True,exist_ok=True)
    facts=library(root/'产出/自动交付');known=root/'记忆库/运行/产品功能/identity-scopes.json'
    bindings=json.loads(known.read_text())['bindings'] if known.exists() else {}
    seed_ids={f['id'] for f in facts if bindings.get(f['id'],{}).get('alias')=='本人'}
    from .scenes import resolve_snapshot,digest_bytes
    snapshot=resolve_snapshot(root/'产出/大模型分析素材/每日场景-v2')
    receipt=json.loads((snapshot/'receipt.json').read_text());raw={}
    for name,sha in receipt['artifacts'].items():
        if not name.endswith('_utterances.json'):continue
        if digest_bytes(snapshot/name)!=sha:raise ValueError('原文快照已变化')
        raw.update({e['id']:e for e in json.loads((snapshot/name).read_text())['utterances']})
    candidates={}
    for f in facts:
        if f.get('sourceMedium') in {'media','podcast','broadcast'}:continue
        for e in f['evidence']:
            duration=e['endOffsetSeconds']-e['startOffsetSeconds']
            if not 4<=duration<=15 or len(e.get('speakers',[]))!=1 or len(e['quote'])<15:continue
            row=raw[e['id']]
            if any(row[k]!=e[k] for k in ('sourceSHA256','startOffsetSeconds','endOffsetSeconds')):raise ValueError('样本来源不符')
            sid='sample-'+checksum({'source':e['sourceSHA256'],'start':e['startOffsetSeconds'],'end':e['endOffsetSeconds']})[:24]
            candidates[sid]={'id':sid,'evidenceId':e['id'],'sourceSHA256':e['sourceSHA256'],'sourceFile':e['sourceFile'],
                             'start':e['startOffsetSeconds'],'end':e['endOffsetSeconds'],'recordedStart':e['start'],
                             'text':row['text'],'speakerScope':e['speakers'][0],'factId':f['id'],'priorUserConfirmed':f['id'] in seed_ids or candidates.get(sid,{}).get('priorUserConfirmed',False)}
    rows=sorted(candidates.values(),key=lambda s:(not s['priorUserConfirmed'],s['recordedStart']))
    selected=[];scopes=set();files={}
    for s in rows:
        if len(selected)>=limit:break
        if s['speakerScope'] in scopes or files.get(s['sourceFile'],0)>=2:continue
        selected.append(s);scopes.add(s['speakerScope']);files[s['sourceFile']]=files.get(s['sourceFile'],0)+1
    body={'schemaVersion':1,'samples':selected,'selection':'single anonymous candidate, 4-15 seconds, retained-content evidence; no claim of clean speech or identity'}
    body['sha256']=checksum(body)
    if persist:write_json(folder/'batch.json',body)
    return body


def state(root):
    folder=home(root);p=folder/'batch.json'
    if not p.exists():return {'samples':[],'labels':{},'counts':{'self':0,'other':0,'unclear':0},'matching':'not_ready'}
    batch=json.loads(p.read_text());expected=checksum({k:v for k,v in batch.items() if k!='sha256'})
    if batch['sha256']!=expected:raise ValueError('校准样本清单已改变')
    labels_path=folder/'labels.json';labels=json.loads(labels_path.read_text()) if labels_path.exists() else {'labels':{},'history':[]}
    current={s['id']:labels['labels'][s['id']] for s in batch['samples'] if s['id'] in labels['labels']}
    counts={kind:sum(v['decision']==kind for v in current.values()) for kind in ('self','other','unclear')}
    features_path=folder/'features.json'
    features=json.loads(features_path.read_text()) if features_path.exists() else {}
    ready=sum(s['id'] in features and features[s['id']].get('dimension')==256 for s in batch['samples'])
    return {**batch,'labels':current,'counts':counts,'featureCount':ready,
            'matching':'awaiting_user_self_samples' if not counts['self'] else 'awaiting_cross_recording_validation',
            'boundary':'校准确认仅作用于所选片段；模型相似度不能直接变成人物确认。'}


def label(root,request):
    batch=state(root)
    if request.get('batchSHA256')!=batch.get('sha256'):raise ValueError('样本版本已变化，请刷新')
    sample=next((s for s in batch['samples'] if s['id']==request.get('sampleId')),None)
    if not sample or request.get('decision') not in {'self','other','unclear','revoke'}:raise ValueError('校准操作无效')
    # Bind the visible user operation to unchanged original evidence and offsets.
    original=evidence(root,sample['evidenceId'])
    if original['sourceSHA256']!=sample['sourceSHA256'] or original['startOffsetSeconds']!=sample['start'] or original['endOffsetSeconds']!=sample['end']:raise ValueError('样本来源已变化')
    p=home(root)/'labels.json';data=json.loads(p.read_text()) if p.exists() else {'labels':{},'history':[]}
    operation={'sampleId':sample['id'],'evidenceId':sample['evidenceId'],'sourceSHA256':sample['sourceSHA256'],'start':sample['start'],'end':sample['end'],'decision':request['decision'],'basis':'explicit user selection in self-voice calibration UI'}
    if data['labels'].get(sample['id'])==operation:return state(root)
    if request['decision']=='revoke':data['labels'].pop(sample['id'],None)
    else:data['labels'][sample['id']]=operation
    data['history'].append(operation);write_json(p,data)
    return state(root)


def my_view(root):
    batch=state(root);records=[]
    for sample in batch['samples']:
        decision=batch['labels'].get(sample['id'],{}).get('decision')
        if decision!='self':continue
        row=evidence(root,sample['evidenceId'])
        if row['sourceSHA256']!=sample['sourceSHA256'] or row['startOffsetSeconds']!=sample['start'] or row['endOffsetSeconds']!=sample['end']:raise ValueError('已确认片段来源改变')
        records.append({**row,'attribution':'user_confirmed_clip','date':row['start'][:10]})
    records.sort(key=lambda r:r['start'],reverse=True)
    from .scenes import digest_bytes
    candidates=[];report=None;stale=False
    for name in ('probe.json','calibration-report.json'):
        path=home(root)/name
        if not path.exists():continue
        item=json.loads(path.read_text())
        fresh=item.get('referenceBatchSHA256')==batch.get('sha256') and item.get('labelStateSHA256')==checksum(batch['labels']) and item.get('helperSHA256')==digest_bytes(Path(root)/'scripts/voice_embedding.swift') and item.get('matchingImplementationSHA256')==digest_bytes(Path(root)/'scripts/soundlog_memory/voice_features.py')
        if not fresh:stale=True;continue
        if name=='probe.json':candidates=[r for r in item['rows'] if r['attribution']=='possible_self']
        else:report={k:item[k] for k in ('evaluated','falsePositiveSelf','selfRecovered','selfEvaluated')}
    return {'records':records,'confirmedClips':len(records),'otherClips':batch['counts']['other'],
            'candidates':candidates,'calibration':report,'matchingNeedsRefresh':stale,
            'boundary':'本人确认限定于这些声音片段；说过的话仍不自动等于事实、承诺或已完成事项。'}


def confirmed_roles(root):
    path=home(root)/'labels.json'
    if not path.exists():return {}
    data=json.loads(path.read_text())
    return {r['evidenceId']:r for r in data['labels'].values() if r['decision'] in {'self','other'}}


def annotate_evidence(row,roles):
    label=roles.get(row['id'])
    if not label or row.get('sourceSHA256')!=label['sourceSHA256'] or row.get('startOffsetSeconds')!=label['start'] or row.get('endOffsetSeconds')!=label['end']:return row
    return {**row,'voiceAttribution':{'role':label['decision'],'basis':'user_confirmed_clip','scope':'this_evidence_only'}}
