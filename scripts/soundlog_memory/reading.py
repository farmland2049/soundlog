"""Publish reviewed topic summaries over immutable candidate facts, without memory writes."""
import fcntl
import os
from pathlib import Path
import shutil
import tempfile
from .evidence import read_json, digest
from .scenes import digest_bytes
from .products import FUNCTIONS, text
from .store import write_json


def load_verified_result(root, rid):
    import re
    root=Path(root).resolve()
    if not isinstance(rid,str) or not re.fullmatch(r'product-[a-f0-9]{24}',rid):
        raise ValueError('结果编号无效')
    source=root/'results'/rid; receipt=read_json(source/'receipt.json')
    if receipt['resultId']!=rid:
        raise ValueError('结果回执编号不一致')
    for name,sha in receipt['artifacts'].items():
        if Path(name).name!=name or digest_bytes(source/name)!=sha:
            raise ValueError('来源工件缺失或改变')
    facts=read_json(source/'facts.json')['facts']
    return receipt, facts


def publish_reading(root, outline):
    root=Path(root).resolve()
    if not isinstance(outline,dict) or set(outline)!={'schemaVersion','resultId','reviewer','sections'} or outline['schemaVersion']!=1:
        raise ValueError('阅读纲要格式无效')
    reviewer=text(outline['reviewer'],'reviewer')
    import re
    rid=outline['resultId']
    receipt,facts=load_verified_result(root,rid)
    known={f['id']:f for f in facts}
    days=sorted({name[:10] for name in receipt['artifacts'] if re.fullmatch(r'\d{4}-\d{2}-\d{2}_journal\.md',name)})
    sections=outline['sections']
    if not isinstance(sections,list):raise ValueError('sections须为数组')
    selected=set()
    for section in sections:
        if not isinstance(section,dict) or set(section)!={'date','function','title','summary','factIds'}:
            raise ValueError('主题字段无效')
        if section['date'] not in days or section['function'] not in FUNCTIONS:
            raise ValueError('主题日期或功能越界')
        text(section['title'],'主题标题');text(section['summary'],'主题摘要')
        refs=section['factIds']
        if not isinstance(refs,list) or not refs or any(not isinstance(k,str) or k not in known for k in refs):
            raise ValueError('主题必须引用已有事实')
        for key in refs:
            fact=known[key]
            if fact['date']!=section['date'] or section['function'] not in fact['functionUses']:
                raise ValueError('主题引用日期或功能不匹配')
            marker=(section['date'],section['function'],key)
            if marker in selected:raise ValueError('同一功能下重复分配事实')
            selected.add(marker)
    identifier='reading-'+digest({'outline':outline,'sourceReceipt':receipt,'implementation':digest_bytes(Path(__file__))})[:24]
    parent=root/'reading';parent.mkdir(parents=True,exist_ok=True);dest=parent/identifier
    with (root/'.reading.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('阅读版正在生成') from None
        stage=Path(tempfile.mkdtemp(prefix='.reading-',dir=parent))
        try:
            write_json(stage/'outline.json',outline)
            index=['# 录音功能阅读版','',f'来源结果：`{rid}`；状态：{receipt["state"]}。',
                   '仅忠于未经听音校订的机器稿；主体、现场/媒体来源及历史任务当前状态未确认。',
                   '主题摘要由审阅者另行整理，程序只验证来源、范围与引用，不证明语义正确。',
                   f'审阅者：{reviewer}。','', '|日期|每日记录|讨论纪要|待办/安排|学习/灵感|','|---|---|---|---|---|']
            for day in days:
                index.append('|'+day+'|'+'|'.join(f'[{FUNCTIONS[f]}]({day}_{f}.md)' for f in FUNCTIONS)+'|')
                for function,label in FUNCTIONS.items():
                    detail=f'../../results/{rid}/{day}_{function}.md'
                    relevant=[f for f in facts if f['date']==day and function in f['functionUses']]
                    lines=[f'# {day} · {label}（主题阅读版）','',
                           '> 以下为录到的交谈与自述，不自动等同现实活动、本人观点或当前待办。',
                           f'> 原始候选条目 {len(relevant)} 条；全请求状态 {receipt["state"]}。','']
                    for section in sections:
                        if section['date']!=day or section['function']!=function:continue
                        lines += ['## '+section['title'],'',section['summary'],'','依据：'+ '、'.join('`'+k+'`' for k in section['factIds'])+'。','']
                    rest=[f for f in relevant if (day,function,f['id']) not in selected]
                    lines += [f'[全部原话、时间和匿名来源明细]({detail})','',f'<details><summary>其他候选条目（{len(rest)}条，保留回查）</summary>','']
                    for f in rest:lines.append('- '+f['summary']+' `'+f['id']+'`')
                    lines += ['','</details>','']
                    (stage/f'{day}_{function}.md').write_text('\n'.join(lines),encoding='utf-8')
            (stage/'README.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
            artifacts={p.name:digest_bytes(p) for p in stage.iterdir()}
            report={'readingId':identifier,'sourceResultId':rid,'sourceState':receipt['state'],'reviewer':reviewer,
                    'sections':len(sections),'sourceFacts':len(facts),'artifacts':artifacts,
                    'semanticAssessment':'same_agent_review_not_independent_audio_verification'}
            write_json(stage/'receipt.json',report)
            if dest.exists():
                old=read_json(dest/'receipt.json')
                if old['artifacts']!=artifacts or any(digest_bytes(dest/name)!=sha for name,sha in artifacts.items()):
                    raise ValueError('旧阅读版被改变，拒绝覆盖')
            else:os.rename(stage,dest)
            return {**report,'directory':str(dest)}
        finally:
            if stage.exists():shutil.rmtree(stage)
