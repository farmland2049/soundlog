"""Explicit fact-scoped user attribution; no voice matching or propagation."""
import hashlib,json
from pathlib import Path
from .store import write_json


def update(home,operation,authorization):
 digest=hashlib.sha256(json.dumps(operation,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 if authorization.get('operationSHA256')!=digest or not authorization.get('userStatement'):raise ValueError('缺少范围明确的用户身份授权')
 if operation.get('kind') not in {'confirm','revoke'} or not operation.get('factId') or not operation.get('alias'):raise ValueError('身份操作无效')
 home=Path(home);home.mkdir(parents=True,exist_ok=True);path=home/'identity-scopes.json'
 state=json.loads(path.read_text()) if path.exists() else {'bindings':{},'history':[]}
 if any(r['operationSHA256']==digest for r in state['history']):return state
 key=operation['factId']
 if operation['kind']=='confirm':state['bindings'][key]={'alias':operation['alias'],'scope':'fact_only','userStatement':authorization['userStatement']}
 else:state['bindings'].pop(key,None)
 state['history'].append({'operation':operation,'operationSHA256':digest,'userStatement':authorization['userStatement']});write_json(path,state);return state
