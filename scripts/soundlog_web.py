#!/usr/bin/env python3
"""Read-only browser for the selected local soundlog result."""
import argparse
import json
import secrets
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from soundlog import selected, selected_snapshot, PRODUCTS, FUNCTIONS
from soundlog_memory.unified_search import search_soundlog
from soundlog_memory.scenes import digest_bytes

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Soundlog 本地记录</title><style>
body{font:16px/1.6 -apple-system,sans-serif;max-width:1000px;margin:auto;padding:24px;background:#f5f6f4;color:#202824}h1{margin-bottom:0}.hint{color:#526159}section,.card{background:white;border:1px solid #dce3dd;border-radius:12px;padding:16px;margin:14px 0}label{margin-right:12px}select,input,button{font:inherit;padding:8px;border:1px solid #abb9ad;border-radius:6px}button{background:#234d3a;color:white;cursor:pointer}details{margin-top:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:#45554b}.meta{font-size:.88em;color:#607068}.error{color:#a12d27}
</style><h1>Soundlog 本地记录</h1><p class="hint">机器转写整理的候选，人物与事项状态尚未确认。选择日期和栏目，或搜索原文与候选。</p><p id="coverage" class="hint"></p><section><label>日期 <select id="day"></select></label><label>栏目 <select id="kind"><option value="journal">每日记录</option><option value="minutes">讨论纪要</option><option value="actions">待办与安排</option><option value="learning">学习与灵感</option></select></label><button id="show">查看</button> <button id="topics">按主题查看</button></section><section><label for="q">关键词</label> <input id="q" placeholder="输入要找的词"><label><input type="checkbox" id="all-days"> 搜索全部日期</label> <button id="search">搜索</button><p class="hint">可搜索所选日期或全部日期；结果分为原文与功能候选，关键词检索不自动回答问题。</p></section><div id="result" aria-live="polite"></div><script>
const root=location.pathname.replace(/\\/$/,''); const out=document.querySelector('#result');
function el(tag,text,cls){let n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n}
const labels={explicit:'原话明确表达',reported:'转述或自述',suggestion:'建议或意向',question:'疑问',negated:'否定',uncertain:'含糊待核实',hypothetical:'假设举例'};
const taskLabels={question:'待澄清的问题',proposal:'建议或备选意向',request:'提出的要求',commitment:'当时的承诺',reported_completed:'原话称已完成',reported_cancelled:'原话称已取消',reported_rescheduled:'原话称已改期',unknown:'状态未知'};
function source(e){let offset=typeof e.startOffsetSeconds==='number'?' · 文件内 '+e.startOffsetSeconds.toFixed(2)+' 秒':'';return (e.start||'')+' · '+(e.sourceFile||'')+offset}
function contextControl(e){let box=el('div',''),button=el('button','查看相邻原文'),area=el('div','');button.type='button';button.className='secondary';button.onclick=async()=>{try{let day=(e.start||'').slice(0,10),d=await get('context?'+new URLSearchParams({day,id:e.id}));area.replaceChildren(el('p',d.boundary,'meta'));for(const r of d.rows)area.append(el('pre',(r.id===d.focusId?'▶ ':'')+source(r)+'\\n'+r.text));button.disabled=true}catch(err){area.replaceChildren(el('p',err.message,'error'))}};box.append(button,area);return box}
function card(f){let c=el('article','','card');c.append(el('div',(f.recordedStart||'')+' · '+(labels[f.assertion]||'候选'),'meta'),el('p',f.summary));if(f.taskState)c.append(el('p','录音中的事项性质：'+(taskLabels[f.taskState]||'状态未知')+'；不代表现在的状态。','meta'));if(f.dueText)c.append(el('p','期限原话：'+f.dueText,'meta'));let d=el('details','');d.append(el('summary','查看原文证据'));for(const e of f.evidence||[]){d.append(el('pre',source(e)+'\\n'+(e.quote||e.text||'')),contextControl(e))}c.append(d);return c}
async function get(path){let r=await fetch(root+'/api/'+path,{cache:'no-store'});let j=await r.json();if(!r.ok)throw Error(j.error||'读取失败');return j}
function fail(e){out.replaceChildren(el('p',e.message,'error'))}
async function init(){let d=await get('status');document.querySelector('#coverage').textContent='当前选择包含：'+d.dates.join('、')+'。新录音需生成并选择新结果后才会显示。';let s=document.querySelector('#day');for(const day of d.dates){let o=el('option',day);o.value=day;s.append(o)}s.value=d.dates[d.dates.length-1];await show()}
async function show(){try{let day=document.querySelector('#day').value,kind=document.querySelector('#kind').value;let d=await get('items?'+new URLSearchParams({day,kind}));out.replaceChildren(el('h2',day+' · '+document.querySelector('#kind').selectedOptions[0].text),el('p',d.items.length?'共 '+d.items.length+' 条候选':'当前结果在此栏目没有候选。','hint'));for(const f of d.items)out.append(card(f))}catch(e){fail(e)}}
async function search(){try{let q=document.querySelector('#q').value.trim();if(!q)throw Error('请输入关键词');let day=document.querySelector('#all-days').checked?'':document.querySelector('#day').value;let d=await get('search?'+new URLSearchParams({day,q}));out.replaceChildren(el('h2','原文 · '+d.rawEvidence.totalMatches+' 条'));for(const e of d.rawEvidence.matches){let c=el('article','','card');c.append(el('div',source(e),'meta'),el('p',e.text),contextControl(e));out.append(c)}out.append(el('h2','功能候选 · '+d.functionalCandidates.totalMatches+' 条'));for(const x of d.functionalCandidates.matches)out.append(card(x.fact));out.append(el('p','每路最多显示前 100 条；候选可仅因摘要命中。','hint'))}catch(e){fail(e)}}
async function showTopics(){try{let day=document.querySelector('#day').value,kind=document.querySelector('#kind').value;let d=await get('topics?'+new URLSearchParams({day,kind}));out.replaceChildren(el('h2',day+' · 主题'));if(!d.topics.length)out.append(el('p','当前栏目没有主题，可查看全部候选。','hint'));for(const t of d.topics){let section=el('section','');section.append(el('h3',t.title),el('p',t.summary));for(const f of t.items)section.append(card(f));out.append(section)}}catch(e){fail(e)}}
document.querySelector('#show').onclick=show;document.querySelector('#topics').onclick=showTopics;document.querySelector('#search').onclick=search;document.querySelector('#q').onkeydown=e=>{if(e.key==='Enter')search()};init().catch(fail);
</script></html>'''


def handler(token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            url = urlsplit(self.path)
            prefix = '/' + token
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or not (url.path == prefix or url.path.startswith(prefix + '/')):
                self.send_error(404); return
            try:
                if url.path in (prefix, prefix + '/'):
                    return self.reply(200, PAGE.encode(), 'text/html; charset=utf-8')
                row, receipt, facts = selected()
                params = parse_qs(url.query)
                if url.path == prefix + '/api/status':
                    result = {'dates': row['dates'], 'resultId': row['resultId']}
                elif url.path == prefix + '/api/items':
                    day = params.get('day', [''])[0]; kind = params.get('kind', [''])[0]
                    if day not in row['dates'] or kind not in FUNCTIONS:
                        raise ValueError('日期或栏目无效')
                    result = {'items': [f for f in facts if f['date'] == day and kind in f['functionUses']]}
                elif url.path == prefix + '/api/topics':
                    day = params.get('day', [''])[0]; kind = params.get('kind', [''])[0]
                    if day not in row['dates'] or kind not in FUNCTIONS:
                        raise ValueError('日期或栏目无效')
                    reading_id = row['readingId']
                    if not re.fullmatch(r'reading-[a-f0-9]{24}', reading_id):
                        raise ValueError('阅读版编号无效')
                    folder = PRODUCTS / 'reading' / reading_id
                    receipt_path = folder / 'receipt.json'
                    reading_receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                    outline_path = folder / 'outline.json'
                    if (reading_receipt.get('readingId') != reading_id or
                            reading_receipt.get('sourceResultId') != row['resultId'] or
                            digest_bytes(outline_path) != reading_receipt.get('artifacts', {}).get('outline.json')):
                        raise ValueError('阅读主题与当前结果不一致')
                    outline = json.loads(outline_path.read_text(encoding='utf-8'))
                    known = {f['id']: f for f in facts}
                    topics = []
                    for section in outline['sections']:
                        if section['date'] != day or section['function'] != kind:
                            continue
                        entries = [known[k] for k in section['factIds']]
                        if any(f['date'] != day or kind not in f['functionUses'] for f in entries):
                            raise ValueError('主题关联与当前结果不一致')
                        topics.append({'title': section['title'], 'summary': section['summary'], 'items': entries})
                    result = {'topics': topics}
                elif url.path == prefix + '/api/context':
                    day = params.get('day', [''])[0]; evidence_id = params.get('id', [''])[0]
                    if day not in row['dates'] or not re.fullmatch(r'ev-[a-f0-9]{24}', evidence_id):
                        raise ValueError('日期或原文编号无效')
                    snapshot = selected_snapshot(receipt)
                    snapshot_receipt = json.loads((snapshot / 'receipt.json').read_text(encoding='utf-8'))
                    name = day + '_utterances.json'; source_path = snapshot / name
                    if digest_bytes(source_path) != snapshot_receipt.get('artifacts', {}).get(name):
                        raise ValueError('原文来源校验失败')
                    utterances = json.loads(source_path.read_text(encoding='utf-8'))['utterances']
                    matching = [i for i, u in enumerate(utterances) if u['id'] == evidence_id]
                    if len(matching) != 1:
                        raise ValueError('原文编号不属于该日期')
                    center = matching[0]; current = utterances[center]
                    same = [u for u in utterances[max(0, center-3):center+4]
                            if u['sourceSHA256'] == current['sourceSHA256']]
                    result = {'focusId': evidence_id, 'rows': same,
                              'boundary': '仅显示同一音频的相邻机器转写，不代表说话人身份或事件关联。'}
                elif url.path == prefix + '/api/search':
                    day = params.get('day', [''])[0]; query = params.get('q', [''])[0]
                    if (day and day not in row['dates']) or not query.strip() or len(query) > 200:
                        raise ValueError('日期或关键词无效')
                    snapshot = selected_snapshot(receipt)
                    if day:
                        result = search_soundlog(snapshot, PRODUCTS, [row['resultId']], query, day=day, limit=100)
                    else:
                        parts = [search_soundlog(snapshot, PRODUCTS, [row['resultId']], query, day=d, limit=100)
                                 for d in sorted(set(row['dates']))]
                        result = {'query': query, 'date': None, 'boundary': '只检索当前选择的日期；每路最多展示100条。'}
                        for key in ('rawEvidence', 'functionalCandidates'):
                            result[key] = {'totalMatches': sum(p[key]['totalMatches'] for p in parts),
                                           'matches': [m for p in parts for m in p[key]['matches']][:100]}
                else:
                    self.send_error(404); return
                self.reply(200, json.dumps(result, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.reply(400, json.dumps({'error': str(exc)}, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        def reply(self, code, body, kind):
            self.send_response(code); self.send_header('Content-Type', kind); self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store'); self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser(description='仅在本机启动只读录音浏览页面')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    selected()  # fail before opening the server if the selection is invalid
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(token))
    print(f'本地页面：http://127.0.0.1:{server.server_port}/{token}/', flush=True)
    print('按 Ctrl+C 停止。页面只展示机器稿候选和原文。', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == '__main__': main()
