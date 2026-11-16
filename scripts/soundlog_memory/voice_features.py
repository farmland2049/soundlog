"""Existing local acoustic models only; no downloads and no identity auto-confirmation."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from .audio_access import open_verified
from .scenes import digest_bytes
from .store import write_json
from .voice_calibration import state,home,checksum


def model_directory(root):
    root=Path(root)
    manifest_path=root/'Sources/SoundlogCore/ModelManifests/speaker-diarization-coreml-v0.17.7.json'
    manifest=json.loads(manifest_path.read_text())
    base=Path(os.environ.get('SOUNDLOG_FLUIDAUDIO_MODELS_DIR',str(Path.home()/'Library/Application Support/FluidAudio/Models')))/'speaker-diarization'
    for item in manifest['assets']:
        path=base/item['path']
        if not path.is_file() or path.stat().st_size!=item['size'] or digest_bytes(path)!=item['sha256']:
            raise ValueError('Existing acoustic model cache missing or changed; downloads disabled')
    return base,digest_bytes(manifest_path)


def extract(root,samples=None):
    root=Path(root).resolve();folder=home(root);folder.mkdir(parents=True,exist_ok=True)
    samples=state(root)['samples'] if samples is None else samples
    models,model_sha=model_directory(root)
    source=root/'scripts/voice_embedding.swift';binary=folder/'voice-embed';build=folder/'voice-build.json'
    source_sha=digest_bytes(source)
    old=json.loads(build.read_text()) if build.exists() else {}
    if not binary.exists() or old.get('sourceSHA256')!=source_sha or old.get('binarySHA256')!=digest_bytes(binary):
        subprocess.run(['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)','swiftc',str(source),'-o',str(binary)],check=True,capture_output=True,text=True)
        write_json(build,{'sourceSHA256':source_sha,'binarySHA256':digest_bytes(binary)})
    path=folder/'features.json';features=json.loads(path.read_text()) if path.exists() else {}
    for sample in samples:
        identity=checksum({'sample':sample,'modelSHA256':model_sha,'sourceSHA256':source_sha})
        if features.get(sample['id'],{}).get('inputSHA256')==identity:continue
        handle,row,size=open_verified(root,sample['evidenceId'])
        try:
            if row['sourceSHA256']!=sample['sourceSHA256'] or row['startOffsetSeconds']!=sample['start'] or row['endOffsetSeconds']!=sample['end']:raise ValueError('Acoustic sample no longer matches original evidence')
            st=os.fstat(handle.fileno())
            candidates=[p for p in (root/'录音/已归档').rglob(row['sourceFile']) if not p.is_symlink() and p.is_file() and (p.stat().st_ino,p.stat().st_dev)==(st.st_ino,st.st_dev)]
            if not candidates:raise ValueError('Verified source path no longer present')
            result=subprocess.run(['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)',str(binary),str(models),str(candidates[0]),str(sample['start']),str(sample['end'])],capture_output=True,text=True,check=True,timeout=60)
            value=json.loads(result.stdout);v=value['embedding']
            if len(v)!=256 or not all(math.isfinite(x) for x in v) or abs(sum(x*x for x in v)-1)>.01:raise ValueError('Invalid model vector')
            features[sample['id']]={**value,'inputSHA256':identity,'sourceSHA256':sample['sourceSHA256'],'modelManifestSHA256':model_sha,'helperSHA256':source_sha}
            write_json(path,features)
        finally:handle.close()
    return {'samples':len(samples),'features':sum(s['id'] in features for s in samples),'dimension':256,'network':'denied','identityConfirmation':'not_performed'}


def similarities(root):
    batch=state(root);p=home(root)/'features.json';features=json.loads(p.read_text()) if p.exists() else {}
    positives=[s for s in batch['samples'] if batch['labels'].get(s['id'],{}).get('decision')=='self' and s['id'] in features]
    if not positives:return {'status':'awaiting_user_self_samples','scores':[],'confirmedIdentitiesCreated':0}
    rows=[]
    for s in batch['samples']:
        if s['id'] not in features:continue
        # Exclude same recording: do not call template self-similarity validation.
        refs=[r for r in positives if r['sourceSHA256']!=s['sourceSHA256']]
        scores=[sum(a*b for a,b in zip(features[s['id']]['embedding'],features[r['id']]['embedding'])) for r in refs]
        rows.append({'sampleId':s['id'],'score':sum(scores)/len(scores) if scores else None,'referenceRecordings':len({r['sourceSHA256'] for r in refs}),'userDecision':batch['labels'].get(s['id'],{}).get('decision'),'identity':'unconfirmed'})
    return {'status':'cross_recording_scores_only','scores':rows,'scoreMeaning':'cosine similarity, not probability or identity confirmation','confirmedIdentitiesCreated':0,'threshold':'not_calibrated'}


def calibrate(root):
    batch=state(root);p=home(root)/'features.json';features=json.loads(p.read_text()) if p.exists() else {}
    labelled=[s for s in batch['samples'] if s['id'] in features and batch['labels'].get(s['id'],{}).get('decision') in {'self','other'}]
    def score(query,refs):
        # Nearest confirmed voice example, excluding the same original recording.
        values=[sum(a*b for a,b in zip(features[query['id']]['embedding'],features[r['id']]['embedding'])) for r in refs if r['sourceSHA256']!=query['sourceSHA256']]
        return max(values) if values else None
    folds=[]
    for source in sorted({s['sourceSHA256'] for s in labelled}):
        train=[s for s in labelled if s['sourceSHA256']!=source]
        positives=[s for s in train if batch['labels'][s['id']]['decision']=='self']
        negatives=[s for s in train if batch['labels'][s['id']]['decision']=='other']
        if len({s['sourceSHA256'] for s in positives})<2 or len(negatives)<2:continue
        negative_scores=[score(s,positives) for s in negatives]
        negative_scores=[s for s in negative_scores if s is not None]
        if not negative_scores:continue
        threshold=max(negative_scores)+.03
        for sample in [s for s in labelled if s['sourceSHA256']==source]:
            value=score(sample,positives)
            folds.append({'sampleId':sample['id'],'heldOutRecording':source,'userDecision':batch['labels'][sample['id']]['decision'],
                          'score':value,'thresholdFromOtherRecordings':threshold,'predicted':'possible_self' if value is not None and value>=threshold else 'unknown'})
    fp=sum(r['predicted']=='possible_self' and r['userDecision']=='other' for r in folds)
    tp=sum(r['predicted']=='possible_self' and r['userDecision']=='self' for r in folds)
    self_total=sum(r['userDecision']=='self' for r in folds)
    report={'status':'calibration_only','matchingImplementationSHA256':digest_bytes(Path(__file__)),'labelStateSHA256':checksum(batch['labels']),'referenceBatchSHA256':batch['sha256'],
            'helperSHA256':digest_bytes(Path(root)/'scripts/voice_embedding.swift'),
            'method':'leave-one-recording-out; nearest positive template; negative training maximum plus 0.03 margin',
            'folds':folds,'evaluated':len(folds),'falsePositiveSelf':fp,'selfRecovered':tp,'selfEvaluated':self_total,
            'boundary':'This is small-sample calibration with a method selected during development, not an independent production accuracy estimate. No labels propagated.'}
    write_json(home(root)/'calibration-report.json',report)
    return report


def probe(root,limit=40):
    from .voice_calibration import prepare
    batch=state(root);pool=prepare(root,limit=limit,persist=False)['samples']
    extract(root,pool)
    features=json.loads((home(root)/'features.json').read_text())
    refs=[s for s in batch['samples'] if batch['labels'].get(s['id'],{}).get('decision')=='self']
    negatives=[s for s in batch['samples'] if batch['labels'].get(s['id'],{}).get('decision')=='other']
    if len(refs)<2 or len(negatives)<2:raise ValueError('More confirmed positive and negative samples required')
    def score(s):
        values=[sum(a*b for a,b in zip(features[s['id']]['embedding'],features[r['id']]['embedding'])) for r in refs if r['sourceSHA256']!=s['sourceSHA256']]
        return max(values) if values else None
    threshold=max(v for s in negatives if (v:=score(s)) is not None)+.05
    rows=[]
    for sample in pool:
        if sample['id'] in batch['labels']:continue
        value=score(sample)
        rows.append({**sample,'score':value,'attribution':'possible_self' if value is not None and value>=threshold else 'unknown'})
    result={'status':'pilot_candidates_only','matchingImplementationSHA256':digest_bytes(Path(__file__)),'threshold':threshold,'referenceBatchSHA256':batch['sha256'],
            'helperSHA256':digest_bytes(Path(root)/'scripts/voice_embedding.swift'),
            'labelStateSHA256':checksum(batch['labels']),'rows':rows,
            'boundary':'Small-sample provisional matches. Not user-confirmed identities; no propagation to other utterances or speaker IDs.'}
    write_json(home(root)/'probe.json',result);return {'probes':len(rows),'possibleSelf':sum(r['attribution']=='possible_self' for r in rows),'threshold':threshold,'confirmedIdentitiesCreated':0}
