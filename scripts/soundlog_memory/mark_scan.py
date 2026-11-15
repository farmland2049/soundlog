"""Locate possible spoken markers without treating them as execution authority."""
import json
from .scenes import resolve_snapshot,digest_bytes

TOKENS=('标记一下','这个记住','记住一下','帮我整理','帮我写')

def candidates(root):
 snapshot=resolve_snapshot(root);receipt=json.loads((snapshot/'receipt.json').read_text());found=[]
 for name,sha in receipt['artifacts'].items():
  if not name.endswith('_utterances.json'):continue
  path=snapshot/name
  if digest_bytes(path)!=sha:raise ValueError('MARK来源工件已改变')
  rows=json.loads(path.read_text())['utterances']
  for n,e in enumerate(rows):
   hits=[t for t in TOKENS if t in e['text']]
   if hits:found.append({'evidenceId':e['id'],'tokens':hits,'source':e,'context':[r for r in rows[max(0,n-2):n+3] if r['sourceSHA256']==e['sourceSHA256']], 'classification':'awaiting_agent','executionAuthorization':False})
 return {'snapshotId':receipt['snapshotId'],'candidates':found,'boundary':'词语检测仅准备上下文；是否重点、媒体引用或现场意图须由agent判断。'}
