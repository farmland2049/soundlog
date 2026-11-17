#!/usr/bin/env python3
"""Read-only MCP stdio interface; newline-delimited JSON-RPC, no dependencies."""
import argparse
import json
import re
import sys
from pathlib import Path
from soundlog_memory.library_tools import library
from soundlog_memory.scenes import resolve_snapshot,digest_bytes,search_evidence

TOOLS=[
 {'name':'soundlog_status','description':'读取交付日期和管线状态','inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
 {'name':'soundlog_search','description':'关键词查询已交付内容和完整原文；返回来源与实际范围','inputSchema':{'type':'object','properties':{'query':{'type':'string'},'date':{'type':'string'}},'required':['query'],'additionalProperties':False}},
 {'name':'soundlog_day','description':'读取某日的有来源内容','inputSchema':{'type':'object','properties':{'date':{'type':'string'}},'required':['date'],'additionalProperties':False}},
 {'name':'soundlog_task','description':'读取历史事项变化与关联证据，当前状态可能未知','inputSchema':{'type':'object','properties':{'id':{'type':'string'}},'required':['id'],'additionalProperties':False}},
 {'name':'soundlog_topic','description':'读取知识卡及明确标记的agent新增联想','inputSchema':{'type':'object','properties':{'id':{'type':'string'}},'required':['id'],'additionalProperties':False}},
 {'name':'soundlog_evidence','description':'按证据ID回查原句、原音偏移及匿名线索','inputSchema':{'type':'object','properties':{'id':{'type':'string'}},'required':['id'],'additionalProperties':False}}]


def call(root,name,args):
 schema=next((t['inputSchema'] for t in TOOLS if t['name']==name),None)
 if schema is None or not isinstance(args,dict) or set(args)-set(schema['properties']) or any(k not in args for k in schema.get('required',[])):raise ValueError('工具或参数无效')
 for k,v in args.items():
  if not isinstance(v,str) or not v.strip() or len(v)>500:raise ValueError('参数文本无效')
 if args.get('date') and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',args['date']):raise ValueError('日期无效')
 root=Path(root);delivery=root/'产出/自动交付';home=root/'记忆库/运行/自动管线';scenes=root/'产出/大模型分析素材/每日场景-v2'
 identity_path=root/'记忆库/运行/产品功能/identity-scopes.json'
 bindings=json.loads(identity_path.read_text())['bindings'] if identity_path.exists() else {}
 from soundlog_memory.voice_calibration import confirmed_roles,annotate_evidence
 roles=confirmed_roles(root)
 def attributed(f):return {**f,'attribution':bindings.get(f['id'],{'alias':None,'scope':'unknown'}),'evidence':[annotate_evidence(e,roles) for e in f['evidence']]}
 if name=='soundlog_status':return {'catalog':json.loads((delivery/'catalog.json').read_text()),'pipeline':json.loads((home/'state.json').read_text()) if (home/'state.json').exists() else {'state':'uninitialized'}}
 if name=='soundlog_search':
  query=args['query'];terms=query.casefold().split();facts=[f for f in library(delivery) if (not args.get('date') or f['date']==args['date']) and all(term in (f['summary']+' '+' '.join(e['quote'] for e in f['evidence'])).casefold() for term in terms)]
  raw=search_evidence(scenes,query,day=args.get('date'),limit=100)
  raw['matches']=[annotate_evidence(e,roles) for e in raw['matches']]
  return {'facts':[attributed(f) for f in facts[:100]],'totalFacts':len(facts),'raw':raw,'boundary':'关键词检索可能漏同义表达；事实/身份仍以原文与确认范围为准。'}
 if name=='soundlog_day':return {'date':args['date'],'facts':[attributed(f) for f in library(delivery) if f['date']==args['date']]}
 if name=='soundlog_task':
  tasks=json.loads((delivery/'task-graph.json').read_text())['tasks'];match=next((t for t in tasks if t['id']==args['id']),None)
  if match is None:raise ValueError('事项不存在')
  from soundlog_memory.personal_items import view
  ids={e['id'] for row in match['timeline'] for e in row['evidence']}
  personal=view(root)
  return {**match,'personalContext':[i for i in personal['items'] if any(e['id'] in ids for e in i['evidence'])],
          'personalAttributionStale':bool(personal['stale'])}
 if name=='soundlog_topic':
  if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',args['id']):raise ValueError('主题编号无效')
  latest=json.loads((delivery/'derived/latest.json').read_text());folder=delivery/'derived'/latest['id'];name='knowledge/'+args['id']+'.json'
  receipt=json.loads((folder/'receipt.json').read_text())
  if receipt['artifacts'].get(name)!=digest_bytes(folder/name):raise ValueError('主题校验失败')
  return json.loads((folder/name).read_text())
 if name=='soundlog_evidence':
  if not re.fullmatch(r'ev-[a-f0-9]{24}',args['id']):raise ValueError('证据编号无效')
  snapshot=resolve_snapshot(scenes);receipt=json.loads((snapshot/'receipt.json').read_text())
  for name,sha in receipt['artifacts'].items():
   if name.endswith('_utterances.json'):
    p=snapshot/name
    if digest_bytes(p)!=sha:raise ValueError('证据文件已改变')
    for e in json.loads(p.read_text())['utterances']:
     if e['id']==args['id']:return annotate_evidence(e,roles)
  raise ValueError('证据不存在')


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent);a=parser.parse_args()
 initialized=False
 for line in sys.stdin:
  identifier=None
  try:
   msg=json.loads(line);identifier=msg.get('id');method=msg.get('method');params=msg.get('params',{})
   if identifier is None:continue
   if method=='initialize':
    initialized=True;result={'protocolVersion':'2024-11-05','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'soundlog-readonly','version':'1.0.0'}}
   elif method=='ping':result={}
   elif not initialized:raise ValueError('须先initialize')
   elif method=='tools/list':result={'tools':TOOLS}
   elif method=='tools/call':
    value=call(a.root,params['name'],params.get('arguments',{}));result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
   else:raise ValueError('方法无效')
   response={'jsonrpc':'2.0','id':identifier,'result':result}
  except (ValueError,OSError,KeyError,TypeError) as e:
   response={'jsonrpc':'2.0','id':identifier,'error':{'code':-32602,'message':str(e)}}
  print(json.dumps(response,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
