"""Prospective semantic evaluation pack, freeze gate, and manual-label scorer."""
from datetime import datetime, timezone
import hashlib
import re
from pathlib import Path

from .evidence import read_json
from .reading import load_verified_result
from .scenes import digest_bytes, resolve_snapshot
from .store import write_json
from .products import load_request


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


def _previously_processed_material(results_root):
    root = Path(results_root)
    used, spans = set(), {}
    if not root.exists():
        return used, spans
    if not root.is_dir():
        raise ValueError('既有结果根目录不是文件夹')
    for receipt_path in sorted(root.glob('results/product-*/receipt.json')):
        receipt = read_json(receipt_path)
        result_id = receipt.get('resultId')
        _, facts = load_verified_result(root, result_id)
        request = load_request(root, receipt.get('requestId'))
        items = {item['key']: item for item in request['items']}
        if len(items) != len(request['items']):
            raise ValueError('既有请求包含重复块编号')

        def remember(row):
            sha, start, end = row.get('sourceSHA256'), row.get('startOffsetSeconds'), row.get('endOffsetSeconds')
            if (not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha)
                    or type(start) not in (int, float) or type(end) not in (int, float)
                    or not 0 <= start < end):
                raise ValueError('既有证据缺少可验证的源哈希或时间范围')
            spans.setdefault(sha, []).append((start, end))

        for fact in facts:
            for ref in fact['evidence']:
                used.add(ref['id'])
                remember(ref)
        coverage_path = receipt_path.parent / 'coverage.json'
        expected = receipt.get('artifacts', {}).get('coverage.json')
        if not expected or not coverage_path.is_file() or digest_bytes(coverage_path) != expected:
            raise ValueError('既有结果的覆盖工件缺失或哈希不符')
        coverage = read_json(coverage_path)
        for row in coverage.get('processed', []):
            if row.get('key') not in items:
                raise ValueError('既有覆盖记录与请求块不一致')
            core = {item['id']: item for item in items[row['key']]['material']['utterances']}
            for evidence in row.get('evidence', []):
                if isinstance(evidence, str):
                    evidence_id = evidence
                elif isinstance(evidence, dict) and isinstance(evidence.get('id'), str):
                    evidence_id = evidence['id']
                else:
                    raise ValueError('既有结果覆盖项的证据ID无效')
                if evidence_id not in core:
                    raise ValueError('既有覆盖记录的证据不在请求块中')
                used.add(evidence_id)
                remember(core[evidence_id])
    merged = {}
    for sha, intervals in spans.items():
        groups = []
        for start, end in sorted(intervals):
            if groups and start <= groups[-1][1]:
                groups[-1] = (groups[-1][0], max(groups[-1][1], end))
            else:
                groups.append((start, end))
        merged[sha] = groups
    return used, merged


def prepare_pack(*, scenes_root, results_root, selection_file, output_file):
    snapshot = resolve_snapshot(scenes_root)
    receipt = read_json(snapshot / 'receipt.json')
    selection = read_json(selection_file)
    if selection.get('schemaVersion') != 1 or not isinstance(selection.get('cases'), list):
        raise ValueError('选择文件必须含schemaVersion=1及cases数组')
    if len(selection['cases']) != 24:
        raise ValueError('必须预先选择24个案例')
    prior_ids, prior_spans = _previously_processed_material(results_root)
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
        for eid in evidence_ids:
            source = source_cache[day][eid]
            sha, start, end = source.get('sourceSHA256'), source.get('startOffsetSeconds'), source.get('endOffsetSeconds')
            if (not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha)
                    or type(start) not in (int, float) or type(end) not in (int, float)
                    or not 0 <= start < end):
                raise ValueError('案例证据缺少可验证的源哈希或时间范围')
            if any(start < prior_end and prior_start < end for prior_start, prior_end in prior_spans.get(sha, [])):
                raise ValueError(f'案例 {case_id} 与已有产品结果处理过的源音频时间范围重叠')
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
        required_fields = {'requiredPoints', 'allowedUnknowns', 'forbiddenInferences'}
        if not isinstance(gold, dict) or not required_fields.issubset(gold) or set(gold) - (required_fields | {'expectedNoOutput'}):
            raise ValueError('每例需填写requiredPoints/allowedUnknowns/forbiddenInferences')
        points = gold['requiredPoints']
        no_output = gold.get('expectedNoOutput', False)
        if type(no_output) is not bool or not isinstance(points, list):
            raise ValueError('留空标志或信息点格式无效')
        if (no_output and points) or (not no_output and not points):
            raise ValueError('留空案例不得有必需信息点；其他案例至少标注一个信息点')
        if no_output and not gold['forbiddenInferences']:
            raise ValueError('留空案例须说明不得生成的内容或原因')
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
    no_output_total = no_output_correct = no_output_false_positives = 0
    for row in case_results:
        case = cases_by_id[row['caseId']]
        points = {p['pointId'] for p in case['gold']['requiredPoints']}
        coverage = row['pointCoverage']
        if not isinstance(coverage, list) or not isinstance(row.get('claims'), list):
            raise ValueError('信息点覆盖与生成陈述须为数组')
        if case['gold'].get('expectedNoOutput', False):
            no_output_total += 1
            if row['claims']:
                no_output_false_positives += 1
            else:
                no_output_correct += 1
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
                    or not isinstance(claim['evidence'], list)
                    or claim['support'] not in SUPPORT_LABELS
                    or not isinstance(claim['violations'], list)
                    or set(claim['violations']) - CRITICAL_VIOLATIONS):
                raise ValueError('生成陈述须含原文引用及人工支持度/错误分类')
            evidence = {r['id']: r['text'] for r in case['sourceRows']}
            if not claim['evidence'] and claim['support'] != 'unsupported':
                raise ValueError('无引文陈述只能标记为无支持')
            for ref in claim['evidence']:
                if (not isinstance(ref, dict) or set(ref) != {'id', 'quote'}
                        or not isinstance(ref['id'], str) or not isinstance(ref['quote'], str)):
                    raise ValueError('生成陈述引文格式无效')
                valid = ref['id'] in evidence and bool(ref['quote']) and ref['quote'] in evidence[ref['id']]
                if not valid and (claim['support'] != 'unsupported' or 'fabricated_quote' not in claim['violations']):
                    raise ValueError('无效引文须标记无支持和捏造引文错误')
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
        'noOutputCases': no_output_total, 'noOutputCorrect': no_output_correct,
        'noOutputFalsePositives': no_output_false_positives,
    }


def blind_cases(frozen):
    """Preserve observable timing and anonymous speaker context, never labels."""
    cases = frozen.get('cases')
    if not isinstance(cases, list) or len(cases) != 24:
        raise ValueError('冻结集必须有24个案例')
    row_fields = ('id', 'text', 'start', 'end', 'sourceFile',
                  'startOffsetSeconds', 'endOffsetSeconds', 'speakers')
    clean = []
    for case in cases:
        rows = [{key: r[key] for key in row_fields} for r in case['sourceRows']]
        if not rows or {r['id'] for r in rows} != set(case['evidenceIds']):
            raise ValueError('案例证据与来源不一致')
        clean.append({'caseId': case['caseId'], 'date': case['date'],
                      'function': case['function'], 'sourceRows': rows})
    if len({case['caseId'] for case in clean}) != 24:
        raise ValueError('案例编号重复')
    return clean


def score_run(frozen_file, review_file, output_file, *, generation_file=None, packet_file=None, prompt_file=None):
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
    binding = None
    paths = (generation_file, packet_file, prompt_file)
    if any(path is not None for path in paths):
        if any(path is None for path in paths):
            raise ValueError('绑定评分须同时提供生成结果、盲态输入与实际提示词')
        generated = read_json(generation_file)
        packet = read_json(packet_file)
        expected_packet_cases = blind_cases(frozen)
        if (packet.get('frozenSHA256') != sha256(frozen_file)
                or set(packet) != {'schemaVersion', 'frozenSHA256', 'cases'}
                or packet.get('schemaVersion') != 1 or packet.get('cases') != expected_packet_cases
                or generated.get('packetSHA256') != sha256(packet_file)
                or generated.get('promptSHA256') != sha256(prompt_file)
                or review.get('generationSHA256') != sha256(generation_file)
                or any(generated.get(k) != review.get(k) for k in ('runId', 'generatedAt', 'promptSHA256'))):
            raise ValueError('评分、生成结果、输入或实际提示词的指纹不一致')
        generated_rows = generated.get('cases')
        if not isinstance(generated_rows, list) or len(generated_rows) != len(expected):
            raise ValueError('生成结果须完整覆盖全部案例')
        by_generated = {r.get('caseId'): r for r in generated_rows}
        if len(by_generated) != len(expected) or set(by_generated) != expected:
            raise ValueError('生成结果案例集合不匹配')
        for row in rows:
            actual = by_generated[row['caseId']].get('claims')
            assessed = row.get('claims')
            if not isinstance(actual, list) or not isinstance(assessed, list):
                raise ValueError('生成和评分陈述须为数组')
            stripped = [{k: claim.get(k) for k in ('claimId', 'text', 'evidence')} for claim in assessed]
            if actual != stripped:
                raise ValueError('评分陈述必须逐条匹配实际生成结果: ' + row['caseId'])
        binding = {'generationSHA256': sha256(generation_file), 'packetSHA256': sha256(packet_file),
                   'promptSHA256': sha256(prompt_file)}
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
                       'holdoutCriticalViolations': 0, 'holdoutNoOutputFalsePositives': 0},
        'passed': (holdout['recall'] >= 0.90 and holdout['evidenceSupportRate'] >= 0.95
                   and holdout['criticalViolationCount'] == 0 and holdout['noOutputFalsePositives'] == 0),
        'assessmentBoundary': ('评分标签由审核者逐项填写；脚本只校验结构、引用、时间和计算指标。'
                               + ('已绑定实际生成内容，但不证明评审独立。' if binding else '未绑定实际生成内容，只能作为流程诊断，不得作为正式验收。')),
        'generationBinding': binding,
    }
    _write_once(output_file, report)
    return {'state': report['state'], 'passed': report['passed'],
            'development': development, 'holdout': holdout, 'output': str(output_file)}
