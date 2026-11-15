"""Explicitly approved, checksum-guarded Basic Memory file exchange.

Only a live MCP readback supplied by the calling agent may confirm the result.
No model, cloud API, embedding, or automatic formal write is invoked here.
"""
import hashlib
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from .store import write_json
from .scenes import digest_bytes


def checksum(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def destination(root,relative):
    root=Path(root)
    if not root.is_dir() or root.is_symlink():raise ValueError('记忆项目根目录无效')
    rel=Path(relative)
    if rel.is_absolute() or '..' in rel.parts or len(rel.parts)<3 or rel.parts[0]!='soundlog' or rel.suffix!='.md':raise ValueError('记忆相对路径越界')
    p=root
    for part in rel.parts:
        p=p/part
        if p.is_symlink():raise ValueError('记忆路径不能穿过符号链接')
    if not p.resolve().is_relative_to(root.resolve()):raise ValueError('记忆路径越界')
    return p


def prepare(root,project_id,records,managed=None):
    managed=managed or {};operations=[];seen=set()
    if not project_id:raise ValueError('须明确正式项目ID')
    for record in records:
        fid=record['id']
        import re
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,100}',fid) or fid in seen:raise ValueError('记忆ID无效或重复')
        seen.add(fid)
        rel='soundlog/exchange/'+fid+'.md';path=destination(root,rel)
        status=record.get('status','candidate')
        if status not in {'candidate','confirmed','revoked'}:raise ValueError('记忆状态无效')
        if status=='confirmed' and not record.get('userConfirmation'):raise ValueError('确认状态须有用户确认依据')
        body=record['body']
        if not isinstance(body,str) or not body.strip():raise ValueError('记忆正文为空')
        payload=('---\ntitle: '+json.dumps(record.get('title',fid),ensure_ascii=False)+'\ntype: soundlog_memory\npermalink: soundlog/exchange/'+fid+'\nembed: false\nsoundlog_managed: true\nsoundlog_id: '+fid+'\nstatus: '+status+'\n---\n\n'+body+'\n').encode()
        old=digest_bytes(path) if path.exists() else None
        if old is not None and (managed.get(rel)!=old or not path.read_text().startswith('---\n') or '\nsoundlog_managed: true\n' not in path.read_text()):raise ValueError('目标已有非托管或已改变内容，拒绝覆盖')
        sha=hashlib.sha256(payload).hexdigest()
        if old==sha:kind='reuse'
        else:kind='update' if old else 'create'
        operations.append({'id':fid,'path':rel,'kind':kind,'expectedSHA256':old,'sha256':sha,'content':payload.decode(),'permalink':'soundlog/exchange/'+fid})
    return {'schemaVersion':1,'projectId':project_id,'targetRoot':str(Path(root).resolve()),'operations':operations,'embed':False}


def apply(plan,authorization,preflight,receipt_path):
    plan_sha=checksum(plan)
    if authorization.get('planSHA256')!=plan_sha or authorization.get('targetRoot')!=plan['targetRoot'] or authorization.get('operationIds')!=[o['id'] for o in plan['operations']]:raise ValueError('授权不匹配具体写入计划')
    now=datetime.now(timezone.utc);checked=datetime.fromisoformat(preflight['checkedAt'].replace('Z','+00:00'))
    if checked.tzinfo is None or not 0<=(now-checked).total_seconds()<=120 or preflight.get('projectId')!=plan['projectId'] or preflight.get('source')!='local' or str(Path(preflight.get('localPath','')).resolve())!=plan['targetRoot']:raise ValueError('正式项目实时预检无效')
    root=Path(plan['targetRoot']);receipt_path=Path(receipt_path)
    if receipt_path.exists():
        previous=json.loads(receipt_path.read_text())
        if previous.get('planSHA256')==plan_sha and previous.get('state') in {'needs_mcp_readback','verified'} and len(previous['operations'])==len(plan['operations']):
            if all(destination(root,o['path']).is_file() and digest_bytes(destination(root,o['path']))==o['sha256'] for o in previous['operations']):
                return previous
        raise ValueError('回执已存在但不满足幂等复用条件，须先核对，不重复执行')
    for o in plan['operations']:
        path=destination(root,o['path']);old=digest_bytes(path) if path.exists() else None
        if old!=o['expectedSHA256'] or hashlib.sha256(o['content'].encode()).hexdigest()!=o['sha256']:raise ValueError('写前校验失败')
    result={'state':'writing','planSHA256':plan_sha,'projectId':plan['projectId'],'targetRoot':str(root),'operations':[]}
    write_json(receipt_path,result)
    try:
        for o in plan['operations']:
            path=destination(root,o['path']);path.parent.mkdir(parents=True,exist_ok=True)
            if o['kind']=='create':
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as stream:stream.write(o['content']);stream.flush();os.fsync(stream.fileno())
            elif o['kind']=='update':
                if digest_bytes(path)!=o['expectedSHA256']:raise ValueError('更新前文件已变化')
                # Keep an immutable prior version beside the private operation receipt.
                backup=receipt_path.parent/'prior-versions'/o['expectedSHA256'];backup.parent.mkdir(exist_ok=True)
                if not backup.exists():
                    with backup.open('xb') as stream:stream.write(path.read_bytes())
                temp=path.with_name('.'+path.name+'.'+plan_sha[:12]+'.tmp')
                with temp.open('x') as stream:stream.write(o['content']);stream.flush();os.fsync(stream.fileno())
                os.replace(temp,path)
            elif o['kind']!='reuse':raise ValueError('未知记忆操作')
            if digest_bytes(path)!=o['sha256']:raise ValueError('写后哈希不匹配')
            result['operations'].append({k:v for k,v in o.items() if k!='content'});write_json(receipt_path,result)
        result['state']='needs_mcp_readback';write_json(receipt_path,result);return result
    except Exception:
        result['state']='needs_reconciliation';write_json(receipt_path,result);raise


def confirm(receipt,metadata):
    if receipt.get('state')!='needs_mcp_readback':raise ValueError('操作未处于MCP待读回状态')
    observed={r['file_path']:r for r in metadata}
    if len(observed)!=len(metadata):raise ValueError('MCP读回重复')
    expected={o['path'] for o in receipt['operations']}
    if set(observed)!=expected:raise ValueError('MCP读回不完整或范围不符')
    for o in receipt['operations']:
        m=observed[o['path']];path=destination(receipt['targetRoot'],o['path'])
        if not path.is_file() or digest_bytes(path)!=o['sha256'] or m.get('checksum')!=o['sha256'] or m.get('permalink')!=o['permalink']:raise ValueError('MCP与文件校验不匹配')
    return {**receipt,'state':'verified','boundary':'调用者须保留真实MCP读回证据；校验元数据不代表语义确认。'}


def reconcile(plan,receipt):
    if receipt.get('planSHA256')!=checksum(plan):raise ValueError('恢复计划不匹配')
    recorded={o['path']:o for o in receipt.get('operations',[])};rows=[]
    for o in plan['operations']:
        path=destination(plan['targetRoot'],o['path']);sha=digest_bytes(path) if path.is_file() else None
        kind='recorded_match' if sha==o['sha256'] and o['path'] in recorded else 'unrecorded_match' if sha==o['sha256'] else 'not_applied' if sha==o['expectedSHA256'] else 'conflict'
        rows.append({'path':o['path'],'state':kind,'checksum':sha})
    return {'state':'needs_reconciliation','rows':rows,'boundary':'仅核对；未记录但匹配的文件不能自动认领、删除或覆盖。'}
