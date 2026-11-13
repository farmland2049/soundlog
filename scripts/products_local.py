#!/usr/bin/env python3
import argparse,json,sys
from pathlib import Path
from soundlog_memory.local_products import LocalOllama,extract_local

p=argparse.ArgumentParser(description='现有本地Ollama模型提炼草稿；只连接127.0.0.1，不下载、不导入记忆')
p.add_argument('--root',type=Path,required=True);p.add_argument('--request',required=True);p.add_argument('--model',required=True)
p.add_argument('--key',action='append');p.add_argument('--port',type=int,default=11434)
a=p.parse_args()
try:
 result=extract_local(a.root,a.request,LocalOllama(a.model,a.port),a.key)
 print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(1 if result['failed'] else 0)
except (ValueError,OSError,KeyError,TypeError) as exc:
 print('本地草稿失败: '+str(exc),file=sys.stderr);sys.exit(2)
