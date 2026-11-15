"""Concrete action drafts, content-bound approvals and idempotent receipts."""
import hashlib
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from .store import write_json


def action_hash(action):
    return hashlib.sha256(json.dumps(action,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def draft(home, action):
    if set(action)!={'kind','title','start','end','calendar','description'} or action['kind']!='calendar_event':raise ValueError('仅支持明确的日历事件草稿')
    if not all(isinstance(action[k],str) and action[k].strip() for k in ('title','calendar')):raise ValueError('标题和目标日历必须明确')
    start=datetime.fromisoformat(action['start']);end=datetime.fromisoformat(action['end'])
    if not start.tzinfo or not end.tzinfo or end<=start:raise ValueError('事件起止须有明确时区且结束晚于开始')
    identity=action_hash(action);folder=Path(home)/'actions'/('action-'+identity[:24]);folder.mkdir(parents=True,exist_ok=True)
    request={'id':folder.name,'action':action,'sha256':identity,'state':'draft'}
    path=folder/'draft.json'
    if path.exists() and json.loads(path.read_text())!=request:raise ValueError('草稿已改变')
    if not path.exists():write_json(path,request)
    lines=['# 日历操作确认稿','',action['title'],'','目标日历：'+action['calendar'],'开始：'+action['start'],'结束：'+action['end'],'说明：'+action['description'],'','状态：草稿；录音历史口令不构成执行授权。','计划哈希：'+identity]
    (folder/'review.md').write_text('\n'.join(lines)+'\n')
    return request


def calendar_script(action,uid,*,delete=False):
    """Use absolute dates and query the actual event before returning success."""
    payload=json.dumps({'action':action,'uid':uid,'delete':delete},ensure_ascii=False)
    return """const data=PAYLOAD;
const app=Application('Calendar'), matching=app.calendars.whose({name:data.action.calendar})();
if(matching.length!==1)throw Error('Target calendar must match exactly once');
const cal=matching[0], marker='[soundlog:'+data.uid+']';
let found=cal.events.whose({description:{_contains:marker}})(), status='existing';
let result;
if(data.delete){for(const event of found)app.delete(event);if(cal.events.whose({description:{_contains:marker}})().length)throw Error('Event still exists');result={status:'revoked',actionId:data.uid};}
else{
 if(!found.length){const event=app.Event({summary:data.action.title,startDate:new Date(data.action.start),endDate:new Date(data.action.end),description:data.action.description+'\\n'+marker});cal.events.push(event);status='created';found=cal.events.whose({description:{_contains:marker}})();}
 if(found.length!==1)throw Error('Event identity is ambiguous');
 const event=found[0];
 result={status:status,uid:event.uid(),title:event.summary(),start:event.startDate().toISOString(),end:event.endDate().toISOString(),calendar:cal.name()};
}
JSON.stringify(result);
""".replace('PAYLOAD',payload)


def execute(home,action_id,approval,*,runner=None,allow_live=False):
    import re
    if not re.fullmatch(r'action-[a-f0-9]{24}',action_id):raise ValueError('操作编号无效')
    folder=Path(home)/'actions'/action_id;d=json.loads((folder/'draft.json').read_text())
    if approval.get('actionSHA256')!=d['sha256'] or approval.get('decision')!='approve' or not approval.get('userAuthorization'):
        raise ValueError('缺少绑定此具体操作的用户授权')
    receipt_path=folder/'receipt.json'
    if receipt_path.exists():
        receipt=json.loads(receipt_path.read_text())
        if receipt.get('state') in {'completed','revoked'}:return receipt
    if runner is None:
        if not allow_live:raise ValueError('实际应用操作需显式允许live执行')
        runner=lambda script: subprocess.run(['osascript','-l','JavaScript','-'],input=script,text=True,capture_output=True,timeout=60,check=False)
    script=calendar_script(d['action'],action_id);(folder/'execution.js').write_text(script)
    write_json(folder/'approval.json',approval);write_json(receipt_path,{'state':'executing','actionId':action_id,'sha256':d['sha256']})
    try:
        r=runner(script)
        output=json.loads(r.stdout) if not r.returncode else {}
        action=d['action']
        if (r.returncode or output.get('status') not in {'created','existing'} or not output.get('uid') or output.get('title')!=action['title'] or output.get('calendar')!=action['calendar'] or any(datetime.fromisoformat(output[k].replace('Z','+00:00'))!=datetime.fromisoformat(action[k]) for k in ('start','end'))):raise ValueError('日历未返回匹配实际内容的读回：'+r.stderr[:300])
        receipt={'state':'completed','actionId':action_id,'sha256':d['sha256'],'application':'Calendar','externalId':output['uid'],'readback':output,'mode':'live' if allow_live else 'test_adapter'}
        write_json(receipt_path,receipt);return receipt
    except Exception as exc:
        write_json(receipt_path,{'state':'failed','actionId':action_id,'error':str(exc)});raise


def revoke(home,action_id,approval,*,runner=None,allow_live=False):
    import re
    if not re.fullmatch(r'action-[a-f0-9]{24}',action_id):raise ValueError('操作编号无效')
    folder=Path(home)/'actions'/action_id;d=json.loads((folder/'draft.json').read_text());receipt=json.loads((folder/'receipt.json').read_text())
    if approval.get('actionSHA256')!=d['sha256'] or approval.get('decision')!='revoke' or not approval.get('userAuthorization'):raise ValueError('撤销需要具体授权')
    if receipt['state']=='revoked':return receipt
    if receipt['state']!='completed':raise ValueError('不是已完成操作，须先核对外部状态')
    if runner is None:
        if not allow_live:raise ValueError('撤销真实日历事件须允许live')
        runner=lambda s:subprocess.run(['osascript','-l','JavaScript','-'],input=s,text=True,capture_output=True,timeout=60)
    r=runner(calendar_script(d['action'],action_id,delete=True))
    if r.returncode or json.loads(r.stdout)!={'status':'revoked','actionId':action_id}:raise ValueError('撤销未核验，保留原回执')
    receipt={**receipt,'state':'revoked'};write_json(folder/'revoke-approval.json',approval);write_json(folder/'receipt.json',receipt);return receipt
