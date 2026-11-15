#!/usr/bin/env python3
"""Prepare integrations; actual writes require per-plan user authorization."""
import argparse,json
from pathlib import Path
from soundlog_memory import memory_exchange,action_outbox,identity_scope
from soundlog_memory.store import write_json
from soundlog_memory.pipeline import Pipeline

def load(p):return json.loads(Path(p).read_text())
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent);sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('memory-prepare');a.add_argument('--target',type=Path,required=True);a.add_argument('--project',required=True);a.add_argument('--records',type=Path,required=True);a.add_argument('--managed',type=Path);a.add_argument('--output',type=Path,required=True)
 a=sub.add_parser('memory-apply');a.add_argument('--plan',type=Path,required=True);a.add_argument('--approval',type=Path,required=True);a.add_argument('--preflight',type=Path,required=True);a.add_argument('--receipt',type=Path,required=True)
 a=sub.add_parser('memory-confirm');a.add_argument('--receipt',type=Path,required=True);a.add_argument('--metadata',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
 a=sub.add_parser('memory-reconcile');a.add_argument('--plan',type=Path,required=True);a.add_argument('--receipt',type=Path,required=True)
 a=sub.add_parser('action-draft');a.add_argument('--file',type=Path,required=True)
 for name in ['action-execute','action-revoke']:
  a=sub.add_parser(name);a.add_argument('--id',required=True);a.add_argument('--approval',type=Path,required=True);a.add_argument('--allow-live',action='store_true')
 a=sub.add_parser('identity');a.add_argument('--operation',type=Path,required=True);a.add_argument('--approval',type=Path,required=True)
 a=p.parse_args();home=a.root/'记忆库/运行/产品功能'
 try:
  with Pipeline(a.root).lock():
   if a.command=='memory-prepare':
    result=memory_exchange.prepare(a.target,a.project,load(a.records),load(a.managed) if a.managed else None);write_json(a.output,result);result={'state':'prepared_not_written','plan':str(a.output),'sha256':memory_exchange.checksum(result),'operations':len(result['operations'])}
   elif a.command=='memory-apply':result=memory_exchange.apply(load(a.plan),load(a.approval),load(a.preflight),a.receipt)
   elif a.command=='memory-confirm':result=memory_exchange.confirm(load(a.receipt),load(a.metadata));write_json(a.output,result)
   elif a.command=='memory-reconcile':result=memory_exchange.reconcile(load(a.plan),load(a.receipt))
   elif a.command=='action-draft':result=action_outbox.draft(home,load(a.file))
   elif a.command=='action-execute':result=action_outbox.execute(home,a.id,load(a.approval),allow_live=a.allow_live)
   elif a.command=='action-revoke':result=action_outbox.revoke(home,a.id,load(a.approval),allow_live=a.allow_live)
   else:result=identity_scope.update(home,load(a.operation),load(a.approval))
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except (OSError,ValueError,KeyError,TypeError) as e:print('联动失败: '+str(e));return 2
if __name__=='__main__':raise SystemExit(main())
