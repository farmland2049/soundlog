"""Per-file audio processing outcomes for the workbench history."""
import json
from pathlib import Path
import re

REQUIRED={'transcription','soundEvents','speakerDiarization','speakerAlignment','unifiedTranscript','inputCoverage','runManifest'}

def history(pipeline):
    outcomes={}
    for path in sorted((pipeline.root/'产出/运行历史').glob('*/*/processing-status.json')):
        if path.is_symlink() or not path.resolve().is_relative_to(pipeline.root.resolve()):continue
        try:
            doc=json.loads(path.read_text());name=Path(doc['sourcePath']).name
            if not re.fullmatch(r'\d{14}\.(mp3|m4a|wav|aac|flac)',name,re.I):continue
            modules=doc['modules']
            complete=all(modules.get(k,{}).get('state')=='completed' for k in REQUIRED)
            failed=[v for v in modules.values() if v.get('state') in {'failed','unsupported','incomplete'}]
            audio='completed' if complete else 'failed' if failed else 'processing'
            old=outcomes.get(name)
            if old and old['updated']>doc.get('updatedAt',''):continue
            outcomes[name]={'name':name,'audioState':audio,
                'recordedTime':name[:4]+'-'+name[4:6]+'-'+name[6:8]+' '+name[8:10]+':'+name[10:12]+':'+name[12:14],
                'date':name[:4]+'-'+name[4:6]+'-'+name[6:8], 'updated':doc.get('updatedAt',''),
                'note':('音频时长校验失败，可重试。' if any('rangeOutsideAudio' in v.get('error','') for v in failed) else '音频处理失败，可重试。') if failed else ''}
        except (OSError,ValueError,KeyError,TypeError):continue
    for folder,state in [(pipeline.root/'录音/已归档','archived'),(pipeline.root/'录音/待处理','waiting')]:
        for path in folder.glob('*'):
            if path.is_symlink() or not path.is_file() or not re.fullmatch(r'\d{14}\.(mp3|m4a|wav|aac|flac)',path.name,re.I):continue
            if path.name not in outcomes:
                name=path.name;outcomes[name]={'name':name,'audioState':state,'recordedTime':name[:4]+'-'+name[4:6]+'-'+name[6:8]+' '+name[8:10]+':'+name[10:12]+':'+name[12:14],'date':name[:4]+'-'+name[4:6]+'-'+name[6:8],'updated':'','note':''}
    return {'files':sorted(outcomes.values(),key=lambda x:x['name'],reverse=True)}
