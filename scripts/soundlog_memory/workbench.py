"""Human/agent review work packets; never classifies unread evidence."""
from pathlib import Path
from .evidence import read_json
from .products import load_request, validate_block, combine_results
from .store import write_json


def create_only(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects prior review and source files.
    with path.open('x', encoding='utf-8') as handle:
        import json
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def prepare(root, rid, output, *, count=10, completed=None):
    if type(count) is not int or not 1 <= count <= 240:
        raise ValueError('count须为1—240')
    request = load_request(root, rid)
    done = set()
    if completed is not None:
        envelope, _ = combine_results(root, [completed])
        if envelope['requestId'] != rid:
            raise ValueError('已审结果属于其他请求')
        done = {b['key'] for b in envelope['results']}
    selected = [i for i in request['items'] if i['key'] not in done][:count]
    packet = {'schemaVersion': 1, 'requestId': rid, 'instructions':
              '逐句审读；事实用rows引用原句，coverage必须显式覆盖全部核心行。contextRows只作参考，不计完成。',
              'blocks': [{'key': i['key'], 'date': i['date'],
                          'rows': i['material']['utterances'],
                          'contextRows': i['material'].get('contextUtterances', []),
                          'facts': [], 'coverage': []} for i in selected]}
    create_only(output, packet)
    return {'requestId': rid, 'selected': len(selected), 'remaining': len(request['items'])-len(done), 'output': str(output)}


def compile_review(root, decisions):
    if not isinstance(decisions, dict) or set(decisions) != {'requestId','processor','blocks'}:
        raise ValueError('审阅输入须含requestId/processor/blocks')
    req = load_request(root, decisions['requestId'])
    known = {i['key']:i for i in req['items']}
    output = {'schemaVersion':1, 'requestId':req['requestId'], 'processor':decisions['processor'], 'results':[]}
    seen = set()
    if not isinstance(decisions['blocks'], list):
        raise ValueError('blocks须为数组')
    for block in decisions['blocks']:
        if set(block) != {'key','facts','coverage'} or block['key'] not in known or block['key'] in seen:
            raise ValueError('块未知、重复或字段无效')
        seen.add(block['key']); item=known[block['key']]
        rows=item['material']['utterances']; contexts=item['material'].get('contextUtterances',[])
        def pick(indices, source):
            if not isinstance(indices,list) or any(type(n) is not int or n<0 or n>=len(source) for n in indices):
                raise ValueError('行号越界或无效')
            return [source[n] for n in indices]
        facts=[]
        for raw in block['facts']:
            raw=dict(raw)
            refs=pick(raw.pop('rows'),rows)+pick(raw.pop('contextRows',[]),contexts)
            if 'evidence' in raw:
                raise ValueError('引用由原句行号生成，不能同时提交evidence')
            fact={'subject':None,'sourceMedium':'unknown','eventTimeText':None,'dueText':None,'taskState':None,**raw,
                  'evidence':[{'id':e['id'],'quote':e['text']} for e in refs]}
            facts.append(fact)
        coverage=[]; covered=set()
        for group in block['coverage']:
            if set(group)!={'rows','disposition','reason'}:
                raise ValueError('覆盖组字段无效')
            for ev in pick(group['rows'],rows):
                if ev['id'] in covered:
                    raise ValueError('覆盖证据重复')
                covered.add(ev['id'])
                coverage.append({'id':ev['id'],'disposition':group['disposition'],'reason':group['reason']})
        result={'key':block['key'],'facts':facts,'coverage':coverage}
        validate_block(result,item)
        output['results'].append(result)
    # Validate envelope processor and compatibility too.
    combine_results(root,[output])
    return output
