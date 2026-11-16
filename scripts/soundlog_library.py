#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from soundlog_memory.library_tools import task_ledger,ask,answer,question_state,expand_question

def main():
 p=argparse.ArgumentParser(description='已交付资料事项与证据问答入口')
 p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
 sub=p.add_subparsers(dest='command',required=True);sub.add_parser('tasks')
 a=sub.add_parser('ask');a.add_argument('question');a.add_argument('--query',action='append',required=True)
 a=sub.add_parser('answer');a.add_argument('--question',required=True);a.add_argument('--file',required=True,type=Path)
 a=sub.add_parser('question-expand');a.add_argument('--question',required=True);a.add_argument('--query',action='append',required=True)
 a=sub.add_parser('question-state');a.add_argument('--question',required=True);a.add_argument('--state',choices=['processing','failed','awaiting_agent'],required=True);a.add_argument('--detail',default='')
 a=p.parse_args();root=a.root;delivery=root/'产出/自动交付';home=root/'记忆库/运行/自动管线'
 try:
  if a.command=='tasks':result=task_ledger(delivery)
  elif a.command=='ask':result=ask(delivery,home,a.question,a.query,root/'产出/大模型分析素材/每日场景-v2' if (root/'产出/大模型分析素材/每日场景-v2/latest.json').exists() else None,project_root=root)
  elif a.command=='question-expand':result=expand_question(delivery,home,a.question,a.query,root/'产出/大模型分析素材/每日场景-v2' if (root/'产出/大模型分析素材/每日场景-v2/latest.json').exists() else None,project_root=root)
  elif a.command=='question-state':result=question_state(home,a.question,a.state,a.detail)
  else:result=answer(home,a.question,json.loads(a.file.read_text()))
  print(json.dumps(result,ensure_ascii=False,indent=2));return 0
 except (OSError,ValueError,KeyError,TypeError) as e:print(str(e));return 2
if __name__=='__main__':raise SystemExit(main())
