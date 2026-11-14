"""Prospective semantic evaluation pack, freeze gate, and manual-label scorer."""
from datetime import datetime, timezone
import hashlib
import re
from pathlib import Path

from .evidence import read_json
from .reading import load_verified_result
from .scenes import digest_bytes, resolve_snapshot
from .store import write_json


FUNCTIONS = {'journal', 'minutes', 'actions', 'learning'}
CRITICAL_VIOLATIONS = {
    'identity_without_evidence', 'media_attribution', 'negation_flip',
    'fabricated_quote', 'fabricated_amount', 'fabricated_due',
}
SUPPORT_LABELS = {'supported', 'partially_supported', 'unsupported'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError('时间戳无效')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('时间戳无效') from None


def _write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as handle:
            import json
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write('\n')
    except FileExistsError:
        raise ValueError('输出已存在，拒绝覆盖: ' + str(path)) from None


def _previously_processed_ids(results_root, snapshot_id):
    root = Path(results_root)
    used = set()
    if not root.exists():
        return used
    if not root.is_dir():
        raise ValueError('既有结果根目录不是文件夹')
    for receipt_path in sorted(root.glob('results/product-*/receipt.json')):
        receipt = read_json(receipt_path)
        if receipt.get('sourceSnapshotId') != snapshot_id:
            continue
        result_id = receipt.get('resultId')
        _, facts = load_verified_result(root, result_id)
        for fact in facts:
            used.update(ref['id'] for ref in fact['evidence'])
        coverage_path = receipt_path.parent / 'coverage.json'
        expected = receipt.get('artifacts', {}).get('coverage.json')
        if not expected or not coverage_path.is_file() or digest_bytes(coverage_path) != expected:
            raise ValueError('既有结果的覆盖工件缺失或哈希不符')
        coverage = read_json(coverage_path)
        for row in coverage.get('processed', []):
            for evidence in row.get('evidence', []):
                if isinstance(evidence, str):
                    used.add(evidence)
                elif isinstance(evidence, dict) and isinstance(evidence.get('id'), str):
                    used.add(evidence['id'])
                else:
                    raise ValueError('既有结果覆盖项的证据ID无效')
    return used


def prepare_pack(*, scenes_root, results_root, selection_file, output_file):
    snapshot = resolve_snapshot(scenes_root)
    receipt = read_json(snapshot / 'receipt.json')
    selection = read_json(selection_file)
    if selection.get('schemaVersion') != 1 or not isinstance(selection.get('cases'), list):
        raise ValueError('选择文件必须含schemaVersion=1及cases数组')
    if len(selection['cases']) != 24:
        raise ValueError('必须预先选择24个案例')
    prior_ids = _previously_processed_ids(results_root, receipt['snapshotId'])
    ids, function_counts, holdout_counts = set(), {}, {}
    selected, source_cache = [], {}
    all_evidence_ids = set()
    for case in selection['cases']:
        if not isinstance(case, dict) or set(case) != {'caseId', 'date', 'function', 'holdout', 'evidenceIds'}:
            raise ValueError('案例选择字段无效')
        case_id, day, function = case['caseId'], case['date'], case['function']
        if (not isinstance(case_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', case_id)
                or not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day)
                or case_id in ids or function not in FUNCTIONS or type(case['holdout']) is not bool):
            raise ValueError('案例编号、功能或留出标志无效')
        ids.add(case_id)
        if day not in source_cache:
            name = day + '_utterances.json'
            source_path = snapshot / name
            expected = receipt.get('artifacts', {}).get(name)
            if not expected or not source_path.is_file() or digest_bytes(source_path) != expected:
                raise ValueError('每日原文工件缺失或哈希不符: ' + day)
            source_cache[day] = {row['id']: row for row in read_json(source_path)['utterances']}
        evidence_ids = case['evidenceIds']
        if (not isinstance(evidence_ids, list) or not evidence_ids or len(evidence_ids) != len(set(evidence_ids))
                or any(not isinstance(eid, str) or eid not in source_cache[day] for eid in evidence_ids)):
            raise ValueError('案例证据ID为空、重复或不在指定日期')
        reused = set(evidence_ids) & prior_ids
        if reused:
            raise ValueError(f'案例 {case_id} 含已有产品结果处理过的证据，不能作为预生成样本')
        if all_evidence_ids.intersection(evidence_ids):
            raise ValueError('不同案例不能重复使用同一原文证据')
        all_evidence_ids.update(evidence_ids)
        function_counts[function] = function_counts.get(function, 0) + 1
        if case['holdout']:
            holdout_counts[function] = holdout_counts.get(function, 0) + 1
        selected.append({
            'caseId': case_id, 'date': day, 'function': function, 'holdout': case['holdout'],
            'evidenceIds': evidence_ids,
            'sourceRows': [source_cache[day][eid] for eid in evidence_ids],
            'gold': {'requiredPoints': [], 'allowedUnknowns': [], 'forbiddenInferences': []},
        })
    if any(function_counts.get(function, 0) < 6 for function in FUNCTIONS):
        raise ValueError('每类功能至少6个案例')
    if sum(c['holdout'] for c in selected) != 8 or any(holdout_counts.get(f, 0) != 2 for f in FUNCTIONS):
        raise ValueError('须留出8个案例且每类功能恰好2个')
    pack = {
        'schemaVersion': 1, 'state': 'annotation_draft',
        'sourceSnapshotId': receipt['snapshotId'], 'sourceSnapshotPath': str(snapshot),
        'sourceReceiptSHA256': digest_bytes(snapshot / 'receipt.json'),
        'selectionSHA256': digest_bytes(selection_file), 'preparedAt': _now(),
        'generationStartedAt': None,
        'instructions': '先对照sourceRows填写gold，再冻结；冻结前不得生成候选。holdout案例仅用于最终评分。',
        'cases': selected,
    }
    _write_once(output_file, pack)
    return {'state': pack['state'], 'cases': len(selected), 'holdout': 8,
            'sourceSnapshotId': receipt['snapshotId'], 'output': str(output_file)}


def freeze_gold(draft_file, output_file):
    draft = read_json(draft_file)
    if draft.get('state') != 'annotation_draft' or draft.get('generationStartedAt') is not None:
        raise ValueError('只能冻结尚未生成候选的标注草稿')
    cases = draft.get('cases')
    if not isinstance(cases, list) or len(cases) != 24:
        raise ValueError('标注集必须有24个案例')
    counts, holdout_counts, case_ids = {}, {}, set()
    for case in cases:
        function = case['function']
        if (function not in FUNCTIONS or case.get('caseId') in case_ids
                or type(case.get('holdout')) is not bool):
            raise ValueError('案例功能无效')
        case_ids.add(case['caseId'])
        counts[function] = counts.get(function, 0) + 1
        if case['holdout']:
            holdout_counts[function] = holdout_counts.get(function, 0) + 1
        gold = case.get('gold')
        if not isinstance(gold, dict) or set(gold) != {'requiredPoints', 'allowedUnknowns', 'forbiddenInferences'}:
            raise ValueError('每例需填写requiredPoints/allowedUnknowns/forbiddenInferences')
        points = gold['requiredPoints']
        if not isinstance(points, list) or not points:
            raise ValueError('每例至少标注一个应保留的信息点')
        row_ids = set(case['evidenceIds'])
        point_ids = set()
        for point in points:
            if (not isinstance(point, dict) or set(point) != {'pointId', 'description', 'evidenceIds'}
                    or not isinstance(point['pointId'], str) or point['pointId'] in point_ids
                    or not isinstance(point['description'], str) or not point['description'].strip()
                    or not isinstance(point['evidenceIds'], list) or not point['evidenceIds']
                    or set(point['evidenceIds']) - row_ids):
                raise ValueError('金标准信息点缺少说明或引用了案例外证据')
            point_ids.add(point['pointId'])
        for field in ('allowedUnknowns', 'forbiddenInferences'):
            if not isinstance(gold[field], list) or any(not isinstance(v, str) or not v.strip() for v in gold[field]):
                raise ValueError(field + ' 必须为文字数组')
    if any(counts.get(f, 0) < 6 for f in FUNCTIONS):
        raise ValueError('每类功能至少6个案例')
    if sum(bool(c['holdout']) for c in cases) != 8 or any(holdout_counts.get(f, 0) != 2 for f in FUNCTIONS):
        raise ValueError('须留出8个案例且每类功能恰好2个')
    frozen = dict(draft)
    frozen.update(state='gold_frozen', frozenAt=_now(), draftSHA256=sha256(draft_file))
    _write_once(output_file, frozen)
    return {'state': frozen['state'], 'cases': len(cases), 'holdout': 8,
            'frozenSHA256': sha256(output_file), 'output': str(output_file)}


def _metrics(case_results, cases_by_id):
    point_total = point_covered = 0
    claim_total = claim_supported = critical_count = 0
    for row in case_results:
        case = cases_by_id[row['caseId']]
        points = {p['pointId'] for p in case['gold']['requiredPoints']}
        coverage = row['pointCoverage']
        coverage_ids = [p.get('pointId') for p in coverage]
        if set(coverage_ids) != points or len(coverage_ids) != len(points):
            raise ValueError('信息点覆盖评分缺失或越界: ' + row['caseId'])
        claim_ids = {c['claimId'] for c in row['claims']}
        if len(claim_ids) != len(row['claims']):
            raise ValueError('同一案例内claimId重复')
        for point in coverage:
            if type(point.get('covered')) is not bool or not isinstance(point.get('claimIds'), list):
                raise ValueError('信息点评分字段无效')
            if set(point['claimIds']) - claim_ids or (point['covered'] and not point['claimIds']):
                raise ValueError('信息点与生成陈述关联无效')
            point_total += 1
            point_covered += int(point['covered'])
        for claim in row['claims']:
            if (set(claim) != {'claimId', 'text', 'evidence', 'support', 'violations'}
                    or not isinstance(claim['claimId'], str) or not claim['claimId']
                    or not isinstance(claim['text'], str) or not claim['text'].strip()
                    or not isinstance(claim['evidence'], list) or not claim['evidence']
                    or claim['support'] not in SUPPORT_LABELS
                    or not isinstance(claim['violations'], list)
                    or set(claim['violations']) - CRITICAL_VIOLATIONS):
                raise ValueError('生成陈述须含原文引用及人工支持度/错误分类')
            evidence = {r['id']: r['text'] for r in case['sourceRows']}
            for ref in claim['evidence']:
                if (not isinstance(ref, dict) or set(ref) != {'id', 'quote'} or ref['id'] not in evidence
                        or not isinstance(ref['quote'], str) or not ref['quote'] or ref['quote'] not in evidence[ref['id']]):
                    raise ValueError('生成陈述引文不属于案例原文')
            claim_total += 1
            claim_supported += int(claim['support'] == 'supported')
            critical_count += len(claim['violations'])
    return {
        'cases': len(case_results), 'requiredPoints': point_total,
        'coveredPoints': point_covered,
        'recall': point_covered / point_total if point_total else 0.0,
        'claims': claim_total, 'supportedClaims': claim_supported,
        'evidenceSupportRate': claim_supported / claim_total if claim_total else 0.0,
        'criticalViolationCount': critical_count,
    }


def score_run(frozen_file, review_file, output_file):
    frozen = read_json(frozen_file)
    if frozen.get('state') != 'gold_frozen':
        raise ValueError('评分基线不是冻结金标准')
    review = read_json(review_file)
    if review.get('frozenSHA256') != sha256(frozen_file):
        raise ValueError('评分使用的冻结金标准指纹不匹配')
    if _timestamp(review.get('generatedAt')) <= _timestamp(frozen['frozenAt']):
        raise ValueError('生成结果必须晚于金标准冻结时间')
    if (not isinstance(review.get('runId'), str) or not review['runId'].strip()
            or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()
            or not re.fullmatch(r'[a-f0-9]{64}', review.get('promptSHA256', ''))):
        raise ValueError('必须记录实际提示词SHA-256')
    expected = {case['caseId'] for case in frozen['cases']}
    rows = review.get('cases')
    if not isinstance(rows, list) or {r.get('caseId') for r in rows} != expected or len(rows) != len(expected):
        raise ValueError('评分案例集合必须与冻结集完全一致')
    by_id = {c['caseId']: c for c in frozen['cases']}
    development_rows = [r for r in rows if not by_id[r['caseId']]['holdout']]
    holdout_rows = [r for r in rows if by_id[r['caseId']]['holdout']]
    development = _metrics(development_rows, by_id)
    holdout = _metrics(holdout_rows, by_id)
    report = {
        'schemaVersion': 1, 'state': 'scored', 'frozenSHA256': sha256(frozen_file),
        'runId': review.get('runId'), 'generatedAt': review['generatedAt'],
        'promptSHA256': review['promptSHA256'], 'reviewer': review.get('reviewer'),
        'development': development, 'holdout': holdout,
        'thresholds': {'holdoutRecall': 0.90, 'holdoutEvidenceSupportRate': 0.95,
                       'holdoutCriticalViolations': 0},
        'passed': (holdout['recall'] >= 0.90 and holdout['evidenceSupportRate'] >= 0.95
                   and holdout['criticalViolationCount'] == 0),
        'assessmentBoundary': '评分标签由审核者逐项填写；脚本只校验结构、引用、时间和计算指标。',
    }
    _write_once(output_file, report)
    return {'state': report['state'], 'passed': report['passed'],
            'development': development, 'holdout': holdout, 'output': str(output_file)}
