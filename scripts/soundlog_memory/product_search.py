"""Read-only keyword retrieval over explicitly selected functional candidates."""
from .evidence import day_bounds
from .products import FUNCTIONS
from .reading import load_verified_result
from .store import normalize


def search_products(root, result_ids, query, *, day=None, function=None,
                    limit=20, offset=0):
    if (type(limit) is not int or not 1 <= limit <= 1000 or
            type(offset) is not int or offset < 0):
        raise ValueError('limit须为1—1000，offset须非负整数')
    if (not isinstance(result_ids, list) or not result_ids or
            any(not isinstance(r, str) for r in result_ids) or
            len(set(result_ids)) != len(result_ids)):
        raise ValueError('须显式选择不重复的功能结果编号')
    if not isinstance(query, str) or not normalize(query).split():
        raise ValueError('请提供非空关键词')
    if day is not None:
        day_bounds(day)
    if function is not None and function not in FUNCTIONS:
        raise ValueError('功能类别无效')
    terms = normalize(query).split()
    requests = set()
    snapshots = set()
    sources = []
    matches = []
    for rid in result_ids:
        receipt, facts = load_verified_result(root, rid)
        if receipt['requestId'] in requests:
            raise ValueError('同一请求不能混用多个修订结果，请先选择采用版本')
        requests.add(receipt['requestId'])
        snapshots.add(receipt['sourceSnapshotId'])
        if len(snapshots) > 1:
            raise ValueError('所选功能结果来自不同证据快照')
        sources.append({'resultId': rid, 'requestId': receipt['requestId'],
                        'state': receipt['state']})
        for fact in facts:
            if day is not None and fact['date'] != day:
                continue
            if function is not None and function not in fact['functionUses']:
                continue
            fields = []
            if all(t in normalize(fact['summary']) for t in terms):
                fields.append('summary')
            evidence_ids = [e['id'] for e in fact['evidence']
                            if all(t in normalize(e['quote']) for t in terms)]
            if evidence_ids:
                fields.append('evidenceQuote')
            if fields:
                matches.append({'resultId': rid, 'fact': fact,
                                'matchFields': fields,
                                'matchedEvidenceIds': evidence_ids})
    matches.sort(key=lambda x: (x['fact']['date'],
                 min(e['start'] for e in x['fact']['evidence']),
                 x['fact']['id'], x['resultId']))
    return {'query': query, 'sources': sources, 'date': day, 'function': function,
            'totalMatches': len(matches), 'limit': limit, 'offset': offset,
            'matches': matches[offset:offset + limit],
            'boundary': '功能候选关键词检索，不是问答。摘要命中不等于原话含该词；'
                        '返回原始引文供复核，不确认主体、来源媒介或历史事项当前状态。'}
