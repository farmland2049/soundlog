#!/usr/bin/env python3
"""Build reviewed task and derived outputs from persisted agent decisions."""
import argparse,json
from pathlib import Path
from soundlog_memory.task_graph import publish_task_graph
from soundlog_memory.derived_products import publish_derived

def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
 sub=p.add_subparsers(dest='command',required=True)
 a=sub.add_parser('tasks');a.add_argument('--links',type=Path,required=True)
 a=sub.add_parser('derive');a.add_argument('--spec',type=Path,required=True)
 a=sub.add_parser('review');a.add_argument('--from',dest='start',required=True);a.add_argument('--to',dest='end',required=True);a.add_argument('--spec',type=Path)
 a=p.parse_args();delivery=a.root/'产出/自动交付';home=a.root/'记忆库/运行/产品功能';home.mkdir(parents=True,exist_ok=True)
 from soundlog_memory.pipeline import Pipeline
 try:
  with Pipeline(a.root).lock():
   if a.command=='tasks':result=publish_task_graph(delivery,home,json.loads(a.links.read_text()))
   elif a.command=='derive':result=publish_derived(delivery,json.loads(a.spec.read_text()),a.root/'产出/大模型分析素材/每日场景-v2')
   else:
    from soundlog_memory.period_review import publish_period_review
    result=publish_period_review(delivery,a.start,a.end,json.loads(a.spec.read_text()) if a.spec else None)
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except (OSError,ValueError,KeyError,TypeError) as e:print('功能交付失败: '+str(e));return 2
if __name__=='__main__':raise SystemExit(main())
