"""Search raw transcript and reviewed functional candidates side by side."""
from pathlib import Path

from .evidence import read_json
from .product_search import search_products
from .reading import load_verified_result
from .scenes import resolve_snapshot, search_evidence


def search_soundlog(scenes_root, product_root, result_ids, query, *, day=None,
                    function=None, limit=20, offset=0):
    snapshot = resolve_snapshot(scenes_root)
    snapshot_receipt = read_json(snapshot / 'receipt.json')
    if not isinstance(result_ids, list) or not result_ids:
        raise ValueError('须显式选择功能结果')
    selected = []
    for result_id in result_ids:
        receipt, _ = load_verified_result(product_root, result_id)
        if receipt.get('state') != 'completed':
            raise ValueError('统一检索只接受完整功能结果')
        if receipt.get('sourceSnapshotId') != snapshot_receipt.get('snapshotId'):
            raise ValueError('原文与功能结果不属于同一证据快照')
        selected.append(result_id)
    raw = search_evidence(scenes_root, query, day=day, limit=limit, offset=offset)
    candidates = search_products(product_root, selected, query, day=day,
                                 function=function, limit=limit, offset=offset)
    return {
        'query': query,
        'date': day,
        'function': function,
        'sourceSnapshotId': snapshot_receipt['snapshotId'],
        'rawEvidence': raw,
        'functionalCandidates': candidates,
        'boundary': '两路关键词结果并列返回。原文命中表示逐字包含查询词；候选命中也可能只命中摘要，须查看其引文。不是自然语言问答或语义等价判定。',
    }
