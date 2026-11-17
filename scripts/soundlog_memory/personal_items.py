"""Reviewed personal meaning, bound to exact user-confirmed voice clips."""
import json
import re
from pathlib import Path
from .audio_access import evidence
from .scenes import digest_bytes
from .store import atomic, write_json
from .voice_calibration import confirmed_roles, annotate_evidence, checksum

KINDS = {'commitment', 'request_to_me', 'expression', 'ignore'}
LABELS = {'commitment': '我的承诺', 'request_to_me': '别人交办我的事',
          'expression': '我的想法与表达', 'ignore': '本轮不生成个人内容'}


def home(root):
    return Path(root)/'产出/自动交付/personal'


def _role(row, roles):
    return annotate_evidence(row, roles).get('voiceAttribution', {}).get('role')


def review(root, spec):
    if spec.get('schemaVersion') != 1 or not spec.get('reviewer') or not isinstance(spec.get('decisions'), list):
        raise ValueError('个人内容方案缺少版本、审阅者或逐项决策')
    roles = confirmed_roles(root)
    decisions = []; seen = set()
    for item in spec['decisions']:
        key = item.get('id', '')
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', key) or key in seen:
            raise ValueError('个人内容编号无效或重复')
        seen.add(key)
        kind = item.get('kind')
        if kind not in KINDS or not item.get('reason') or not item.get('summary') or not item.get('evidence'):
            raise ValueError('个人内容缺少分类、理由、摘要或原文')
        rows = []; ids = set()
        for ref in item['evidence']:
            row = evidence(root, ref['id'])
            if ref['id'] in ids or not ref.get('quote') or ref['quote'] not in row['text']:
                raise ValueError('个人内容引用重复或不受原文支持')
            ids.add(ref['id'])
            rows.append({**row, 'quote': ref['quote']})
        owner = next((e for e in rows if e['id'] == item.get('selfEvidenceId')), None)
        if owner is None or _role(owner, roles) != 'self':
            raise ValueError('个人归属必须由精确的用户确认本人片段支持')
        if kind == 'request_to_me':
            request = next((e for e in rows if e['id'] == item.get('requestEvidenceId')), None)
            proof = item.get('recipientProof', {})
            if (request is None or _role(request, roles) != 'other'
                or request['sourceSHA256'] != owner['sourceSHA256']
                or not 0 <= owner['startOffsetSeconds'] - request['endOffsetSeconds'] <= 90
                or not proof.get('reason') or proof.get('quote') != next(e['quote'] for e in rows if e['id'] == owner['id'])):
                raise ValueError('交办事项须有他人请求、连续本人回应及收件关系审阅依据')
        required = {owner['id']: 'self'}
        if kind == 'request_to_me': required[request['id']] = 'other'
        decisions.append({'id': key, 'kind': kind, 'summary': item['summary'], 'reason': item['reason'],
                          'selfEvidenceId': owner['id'], 'requiredRoles': required,
                          'recordedStart': owner['start'], 'evidence': rows,
                          'recipientProof': item.get('recipientProof'),
                          'recordedState': 'commitment' if kind == 'commitment' else 'request' if kind == 'request_to_me' else 'expression',
                          'currentState': 'unknown', 'due': None})
    return {'schemaVersion': 1, 'reviewer': spec['reviewer'], 'decisions': decisions,
            'reviewBoundary': 'agent审阅机器稿；声音归属由用户确认；未独立核实内容真实性或当前执行状态。'}


def publish(root, spec):
    result = review(root, spec)
    version = 'personal-' + checksum(result)[:24]
    folder = home(root)/version
    if not folder.exists():
        write_json(folder/'review.json', result)
        lines = ['# 我的事项与表达', '', result['reviewBoundary'], '',
                 '没有新录音不能解释为未完成；历史原话不构成当前执行授权。', '']
        for item in result['decisions']:
            lines += ['## ' + LABELS[item['kind']] + ' · ' + item['summary'], '',
                      '录音时间：' + item['recordedStart'], '',
                      '现时状态：未知；明确期限：未提取。', '', '审阅说明：' + item['reason'], '']
            for e in item['evidence']:
                lines += ['> ' + e['quote'], '', e['id'] + ' · ' + e['sourceFile'] + ' · ' + str(e['startOffsetSeconds']) + '秒', '']
        atomic(folder/'personal.md', '\n'.join(lines) + '\n')
    expected = {'review.json': digest_bytes(folder/'review.json'), 'personal.md': digest_bytes(folder/'personal.md')}
    # An existing version must still contain the exact reviewed payload.
    if json.loads((folder/'review.json').read_text()) != result: raise ValueError('个人内容版本发生冲突')
    receipt = folder/'receipt.json'
    if receipt.exists() and json.loads(receipt.read_text()) != expected: raise ValueError('个人内容工件已变化')
    if not receipt.exists(): write_json(receipt, expected)
    write_json(home(root)/'latest.json', {'id': version, 'receiptSHA256': digest_bytes(receipt)})
    return view(root)


def view(root):
    latest = home(root)/'latest.json'
    empty = {'items': [], 'ignored': [], 'stale': [], 'counts': {k: 0 for k in KINDS},
             'boundary': '按已确认声音和逐项语义审阅组织；当前执行状态未知。', 'reviewed': 0}
    if not latest.exists(): return empty
    pointer = json.loads(latest.read_text()); version = pointer.get('id', '')
    if not re.fullmatch(r'personal-[a-f0-9]{24}', version): raise ValueError('个人内容版本无效')
    folder = home(root)/version; receipt = folder/'receipt.json'
    if digest_bytes(receipt) != pointer['receiptSHA256']: raise ValueError('个人内容回执已变化')
    artifacts = json.loads(receipt.read_text())
    if set(artifacts) != {'review.json', 'personal.md'}: raise ValueError('个人内容回执范围无效')
    for name, sha in artifacts.items():
        if digest_bytes(folder/name) != sha: raise ValueError('个人内容工件已变化')
    result = json.loads((folder/'review.json').read_text()); roles = confirmed_roles(root)
    out = {**empty, 'version': version, 'reviewer': result['reviewer'], 'reviewBoundary': result['reviewBoundary']}
    for item in result['decisions']:
        valid = True; rows = []
        for old in item['evidence']:
            row = evidence(root, old['id'])
            if any(row.get(k) != old.get(k) for k in ('sourceSHA256', 'startOffsetSeconds', 'endOffsetSeconds', 'text', 'sourceFile', 'start', 'end')):
                raise ValueError('个人内容原文来源已变化')
            if old['id'] in item['requiredRoles'] and _role(row, roles) != item['requiredRoles'][old['id']]: valid = False
            rows.append(annotate_evidence({**row, 'quote': old['quote']}, roles))
        if not valid:
            out['stale'].append({'id': item['id'], 'reason': '声音确认已撤销或改变，个人内容已隐藏'}); continue
        out['reviewed'] += 1; out['counts'][item['kind']] += 1
        out['ignored' if item['kind'] == 'ignore' else 'items'].append({**item, 'evidence': rows})
    return out
