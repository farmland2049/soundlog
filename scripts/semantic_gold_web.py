#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local human reference-label form for isolated holdout cases."""
import argparse
import hashlib
import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_ROOT = (ROOT / '记忆库/运行/语义验收').resolve()

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>留出案例参考标注</title><style>
body{font:16px/1.6 -apple-system,sans-serif;max-width:960px;margin:auto;padding:24px;background:#f5f6f4;color:#202824}.case{background:white;border:1px solid #dce3dd;border-radius:12px;margin:18px 0;padding:18px}.source{white-space:pre-wrap;background:#f4f6f4;padding:10px;border-radius:8px}.point{border-left:3px solid #81a18b;padding:8px;margin:10px 0}textarea{width:100%;box-sizing:border-box;font:inherit;padding:8px}button{font:inherit;background:#234d3a;color:white;padding:9px 14px;border:0;border-radius:6px;cursor:pointer}.secondary{background:#e6ede7;color:#234d3a}label{display:block}#status{color:#903b25}</style><h1>留出案例参考标注</h1><p>请仅根据机器转写写出应保留的信息。每条信息勾选支持它的原文；身份、时间或来源不明时写入“尚不确定”。转写含糊或案例不适合时，请勿勉强补全。</p><p>这些标注保存在本机，提交一次后不能覆盖。请完成全部 8 条，再点击保存。</p><div id="cases"></div><button id="save">保存参考标注</button><p id="status" aria-live="polite"></p><script>
const root=location.pathname.replace(/\\/$/,'');let cases=[];
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n}
function area(placeholder){let t=document.createElement('textarea');t.rows=2;t.placeholder=placeholder;return t}
function addPoint(container,rows){let div=document.createElement('div');div.className='point';let t=area('写一条原文支持的必要信息');div.append(t,node('p','勾选支持这条信息的原文：'));for(let i=0;i<rows.length;i++){let l=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.value=rows[i].id;l.append(c,document.createTextNode(' 原文 '+(i+1)));div.append(l)}container.append(div)}
async function init(){let r=await fetch(root+'/api/cases',{cache:'no-store'});let d=await r.json();if(!r.ok)throw Error(d.error);cases=d.cases;let wrap=document.querySelector('#cases');for(let c of cases){let box=document.createElement('section');box.className='case';box.dataset.id=c.caseId;box.append(node('h2',c.caseId+' · '+({journal:'日记',minutes:'纪要',actions:'待办',learning:'学习'}[c.function]||c.function)));c.sourceRows.forEach((x,i)=>{let p=node('p','原文 '+(i+1)+' · '+x.start+'\\n'+x.text);p.className='source';box.append(p)});let noneLabel=document.createElement('label'),none=document.createElement('input');none.type='checkbox';none.className='no-output';noneLabel.append(none,document.createTextNode(' 此栏目没有可提炼的内容，应留空'));box.append(noneLabel);let points=document.createElement('div');points.className='points';box.append(node('h3','应保留的信息'),points);addPoint(points,c.sourceRows);let add=node('button','增加信息点');add.type='button';add.className='secondary';add.onclick=()=>addPoint(points,c.sourceRows);box.append(add,node('h3','尚不确定（每行一项，可留空）'));let unknown=area('例如：说话人身份、具体日期');unknown.className='unknown';box.append(unknown,node('h3','不能从原文推出（留空案例请写明原因）'));let forbidden=area('例如：不能认定已完成');forbidden.className='forbidden';box.append(forbidden);wrap.append(box)}}
function lines(s){return s.split('\\n').map(x=>x.trim()).filter(Boolean)}
document.querySelector('#save').onclick=async()=>{try{let rows=[];for(let box of document.querySelectorAll('.case')){let points=[],noOutput=box.querySelector('.no-output').checked;for(let item of box.querySelectorAll('.point')){let description=item.querySelector('textarea').value.trim();let evidenceIds=Array.from(item.querySelectorAll('input:checked')).map(x=>x.value);if(description||evidenceIds.length){if(!description||!evidenceIds.length)throw Error(box.dataset.id+' 的信息点需要文字和证据');points.push({description,evidenceIds})}}let forbidden=lines(box.querySelector('.forbidden').value);if(noOutput&&(points.length||!forbidden.length))throw Error(box.dataset.id+' 标记留空时不能填写信息点，须说明原因');if(!noOutput&&!points.length)throw Error(box.dataset.id+' 至少填写一条有证据的信息点');rows.push({caseId:box.dataset.id,points,expectedNoOutput:noOutput,allowedUnknowns:lines(box.querySelector('.unknown').value),forbiddenInferences:forbidden})}let r=await fetch(root+'/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cases:rows})});let j=await r.json();if(!r.ok)throw Error(j.error);document.querySelector('#status').textContent='已保存。请回到对话告知已完成。';document.querySelector('#save').disabled=true}catch(e){document.querySelector('#status').textContent=e.message}};
init().catch(e=>document.querySelector('#status').textContent=e.message);
</script></html>'''


def validate_labels(draft, submitted):
    expected = {c['caseId']: c for c in draft['cases'] if c.get('holdout') is True}
    if len(expected) != 8 or not isinstance(submitted, dict) or set(submitted) != {'cases'} or not isinstance(submitted['cases'], list):
        raise ValueError('留出案例或提交格式无效')
    rows = submitted['cases']
    if len(rows) != 8 or {r.get('caseId') for r in rows if isinstance(r, dict)} != set(expected):
        raise ValueError('必须完整标注全部8个留出案例')
    output = []
    for row in rows:
        required = {'caseId', 'points', 'allowedUnknowns', 'forbiddenInferences'}
        if not required.issubset(row) or set(row) - (required | {'expectedNoOutput'}):
            raise ValueError('标注字段无效')
        case = expected[row['caseId']]; ids = set(case['evidenceIds']); points = row['points']
        no_output = row.get('expectedNoOutput', False)
        if type(no_output) is not bool or not isinstance(points, list) or len(points) > 100:
            raise ValueError('留空标志或信息点格式无效')
        if (no_output and points) or (not no_output and not points):
            raise ValueError('留空案例不得填写信息点，其他案例至少填写一条')
        normalized=[]
        for index, point in enumerate(points, 1):
            if (not isinstance(point, dict) or set(point) != {'description', 'evidenceIds'}
                or not isinstance(point['description'], str) or not point['description'].strip()
                or len(point['description']) > 2000 or not isinstance(point['evidenceIds'], list)
                or not point['evidenceIds'] or len(point['evidenceIds']) != len(set(point['evidenceIds']))
                or set(point['evidenceIds']) - ids):
                raise ValueError('信息点必须填写文字并选择本案例原文')
            normalized.append({'pointId': f'point-{index}', 'description': point['description'].strip(), 'evidenceIds': point['evidenceIds']})
        gold={'requiredPoints':normalized}
        for field in ('allowedUnknowns', 'forbiddenInferences'):
            value=row[field]
            if not isinstance(value,list) or len(value)>100 or any(not isinstance(x,str) or not x.strip() or len(x)>2000 for x in value):
                raise ValueError('不确定项或禁止推断格式无效')
            gold[field]=[x.strip() for x in value]
        if no_output:
            if not gold['forbiddenInferences']: raise ValueError('留空案例须说明原因')
            gold['expectedNoOutput'] = True
        output.append({'caseId': row['caseId'], 'gold':gold})
    return output


def start_server(draft_path, output_path, port=0):
    draft_path=Path(draft_path).resolve(); output_path=Path(output_path).resolve()
    if not draft_path.is_relative_to(PRIVATE_ROOT) or not output_path.is_relative_to(PRIVATE_ROOT) or draft_path == output_path:
        raise ValueError('标注草稿和输出须位于本地语义验收目录')
    data=draft_path.read_bytes(); sha=hashlib.sha256(data).hexdigest(); draft=json.loads(data)
    if draft.get('state')!='annotation_draft' or draft.get('generationStartedAt') is not None or sum(c.get('holdout') is True for c in draft.get('cases',[]))!=8:
        raise ValueError('需要含8条留出案例、尚未生成的标注草稿')
    if output_path.exists(): raise ValueError('标注输出已存在，拒绝覆盖')
    token=secrets.token_urlsafe(24); prefix='/'+token
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def allowed(self):
            return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}' and (urlsplit(self.path).path==prefix or urlsplit(self.path).path.startswith(prefix+'/'))
        def reply(self,code,body,kind='application/json; charset=utf-8'):
            body=body.encode();self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if not self.allowed():self.send_error(404);return
            path=urlsplit(self.path).path
            if path in (prefix,prefix+'/'):self.reply(200,PAGE,'text/html; charset=utf-8');return
            if path==prefix+'/api/cases':
                cases=[{'caseId':c['caseId'],'function':c['function'],'sourceRows':[{'id':r['id'],'start':r['start'],'text':r['text']} for r in c['sourceRows']]} for c in draft['cases'] if c['holdout']]
                self.reply(200,json.dumps({'cases':cases},ensure_ascii=False));return
            self.send_error(404)
        def do_POST(self):
            if not self.allowed() or urlsplit(self.path).path!=prefix+'/api/save':self.send_error(404);return
            try:
                if self.headers.get('Origin')!=f'http://127.0.0.1:{self.server.server_port}' or self.headers.get_content_type()!='application/json':raise ValueError('请求来源无效')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=256000:raise ValueError('提交长度无效')
                if hashlib.sha256(draft_path.read_bytes()).hexdigest()!=sha:raise ValueError('草稿已变更，请重新打开')
                labels=validate_labels(draft,json.loads(self.rfile.read(length)))
                output_path.parent.mkdir(parents=True,exist_ok=True)
                data={'schemaVersion':1,'draftSHA256':sha,'reviewerType':'human','submittedAt':datetime.now(timezone.utc).isoformat(),'cases':labels}
                fd,temp=tempfile.mkstemp(prefix='.labels-',dir=output_path.parent)
                try:
                    with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n')
                    os.link(temp,output_path)
                finally:os.unlink(temp)
                self.reply(200,json.dumps({'saved':True}))
            except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as e:self.reply(400,json.dumps({'error':str(e)},ensure_ascii=False))
    return ThreadingHTTPServer(('127.0.0.1',port),Handler), token


def main():
    p=argparse.ArgumentParser(description='本地留出案例人工参考标注')
    p.add_argument('--draft',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=0)
    a=p.parse_args();server,token=start_server(a.draft,a.output,a.port)
    print(f'留出案例标注页面：http://127.0.0.1:{server.server_port}/{token}/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
