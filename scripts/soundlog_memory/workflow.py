"""Evidence snapshots, immutable requests, resumable API batches and imports."""
import json
from pathlib import Path
from .engine import MemoryEngine, public_record, revision_hash, validate_candidate
from .evidence import build_evidence, canonical, chunks, digest, read_json
from .protocol import EXTRACT_PROMPT, RESOLVE_PROMPT, PROMPT_VERSION, TEMPLATE
from .store import atomic, now, write_json


class Workflow:
    def __init__(self, store, runs):
        self.store, self.runs = store, Path(runs)

    def prepare(self, day):
        package, manifest = build_evidence(self.runs, day)
        root = self.store.root / '证据' / day / package['fingerprint']
        if not (root / 'sources.json').exists() or not (root / 'evidence.json').exists():
            write_json(root / 'evidence.json', package)
            write_json(root / 'sources.json', manifest)
        write_json(self.store.root / '证据' / day / 'latest.json', {'fingerprint': package['fingerprint']})
        return package, root

    def request(self, day, resolve=False):
        package, _ = self.prepare(day)
        if not package['utterances']:
            raise ValueError('该日期没有有效文字证据')
        if resolve:
            evidence = {e['id']: e for e in package['utterances']}
            items = []
            for record in self.store.records():
                if record['date'] != day or record['lifecycle'] != 'active' or record['status'] != 'candidate':
                    continue
                old = [r for r in self.store.similar(record) if r['id'] != record['id']]
                items.append({'id': 'resolve-' + record['id'], 'candidate': record,
                              'existing': old, 'material': {'candidate': public_record(record),
                                                           'existing': [public_record(r) for r in old]}})
            body = {'phase': 'resolve', 'items': items, 'evidence': evidence}
        else:
            body = {'phase': 'extract', 'items': chunks(package)}
        request = {'schemaVersion': 1, 'date': day, 'evidenceFingerprint': package['fingerprint'],
                   'promptVersion': PROMPT_VERSION, **body}
        request['requestId'] = 'req-' + digest(request)[:24]
        location = self.store.root / '运行/请求' / request['requestId']
        if not (location / 'request.json').exists():
            write_json(location / 'request.json', request)
            template = dict(TEMPLATE, requestId=request['requestId'])
            if resolve:
                template['results'] = [{'chunkId': item['id'], 'proposal': {'action': 'UNRESOLVED', 'target': None, 'reason': '请比较'}} for item in request['items']]
            else:
                template['results'] = [{'chunkId': item['id'], 'candidates': []} for item in request['items']]
            write_json(location / 'result-template.json', template)
            prompt = RESOLVE_PROMPT if resolve else EXTRACT_PROMPT
            atomic(location / 'instructions.md', '# Soundlog 记忆处理\n\n' + prompt + '\n\n将每个 item.material 分别处理，填写 result-template.json；保留 requestId/chunkId。model 填实际处理者。\n')
            # Public file deliberately excludes source manifests and absolute artifact paths.
            write_json(location / 'materials.json', {'requestId': request['requestId'], 'phase': request['phase'],
                                                      'items': [{'chunkId': i['id'], 'material': i['material']} for i in request['items']]})
        return request, location

    def load_request(self, rid):
        import re
        if not isinstance(rid, str) or not re.fullmatch(r'req-[a-f0-9]{24}', rid):
            raise ValueError('请求编号无效')
        request = read_json(self.store.root / '运行/请求' / rid / 'request.json')
        check = {k: v for k, v in request.items() if k != 'requestId'}
        if rid != 'req-' + digest(check)[:24]:
            raise ValueError('请求快照已改变')
        return request

    def import_result(self, envelope):
        if envelope.get('schemaVersion') != 1:
            raise ValueError('结果 schemaVersion 必须为 1')
        request = self.load_request(envelope.get('requestId'))
        if not isinstance(envelope.get('model'), str) or not envelope['model'].strip():
            raise ValueError('必须记录实际 model/处理者')
        results = envelope.get('results')
        if not isinstance(results, list):
            raise ValueError('results 必须为数组')
        known = {i['id']: i for i in request['items']}
        evidence_path = self.store.root / '证据' / request['date'] / request['evidenceFingerprint'] / 'evidence.json'
        package = read_json(evidence_path)
        if package['fingerprint'] != digest({k: v for k, v in package.items() if k != 'fingerprint'}):
            raise ValueError('证据快照校验失败')
        provenance = {'model': envelope['model'], 'promptVersion': request['promptVersion'], 'requestId': request['requestId'],
                      'batchId': 'batch-' + digest(envelope)[:24]}
        previous_report = self.store.root / '运行/导入' / (provenance['batchId'] + '.json')
        if previous_report.exists():
            previous = read_json(previous_report)
            if previous.get('state') == 'completed':
                return {**previous, 'execution': 'reuse'}
        write_json(self.store.root / '运行/导入' / (provenance['batchId'] + '-input.json'), envelope)
        errors, applied, seen = [], [], set()
        for result in results:
            cid = result.get('chunkId') if isinstance(result, dict) else None
            if cid not in known or cid in seen:
                errors.append({'chunkId': cid, 'error': '未知或重复块编号'})
                continue
            seen.add(cid)
            item = known[cid]
            try:
                if request['phase'] == 'resolve':
                    expected = {r['id']: r for r in item['existing']}
                    proposal = result['proposal']
                    target = proposal.get('target')
                    if target is not None:
                        if target not in expected or revision_hash(self.store.get(target)) != revision_hash(expected[target]):
                            raise ValueError('比对目标不在请求内或已改变，请重新导出')
                    current = self.store.get(item['candidate']['id'])
                    if revision_hash(current) != revision_hash(item['candidate']):
                        raise ValueError('候选已改变，请重新导出')
                    evs = {e['id']: e for e in package['utterances']}
                    c = validate_candidate(item['candidate'], evs, request['date'])
                    applied.append(MemoryEngine(self.store).apply(c, {**provenance, 'chunkId': cid}, proposal, set(expected)))
                else:
                    candidates = result.get('candidates')
                    if not isinstance(candidates, list):
                        raise ValueError('块缺少 candidates 数组')
                    evs = self._evidence_map(item['material']['utterances'])
                    for number, raw in enumerate(candidates):
                        try:
                            c = validate_candidate(raw, evs, request['date'])
                            applied.append(MemoryEngine(self.store).apply(c, {**provenance, 'chunkId': cid}))
                        except (ValueError, KeyError, TypeError) as exc:
                            errors.append({'chunkId': cid, 'candidate': number, 'error': str(exc)})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                errors.append({'chunkId': cid, 'error': str(exc)})
        missing = sorted(set(known) - seen)
        report = {'batchId': provenance['batchId'], 'requestId': request['requestId'], 'at': now(),
                  'state': 'completed' if not errors and not missing else 'partial', 'results': applied,
                  'errors': errors, 'missingChunks': missing}
        write_json(self.store.root / '运行/导入' / (provenance['batchId'] + '.json'), report)
        self.store.reindex()
        return report

    def extract(self, day, adapter):
        request, _ = self.request(day)
        identity = getattr(adapter, 'cache_identity', {'model': adapter.identifier})
        batch = 'api-' + digest({'request': request['requestId'], 'adapter': identity})[:24]
        root = self.store.root / '运行/API' / batch
        status = {'id': batch, 'requestId': request['requestId'], 'chunks': {}, 'state': 'running'}
        # Each completed chunk has a durable receipt. Missing/failed chunks retry next run.
        for item in request['items']:
            cid = item['id']
            cached = root / (cid + '.json')
            if cached.exists():
                status['chunks'][cid] = {'state': 'completed', 'execution': 'reuse'}
                continue
            try:
                raw = self._generate(adapter, EXTRACT_PROMPT, item['material'], lambda v: self._validate_extracted(v, item))
                write_json(root / (cid + '-response.json'), raw)
                evs = self._evidence_map(item['material']['utterances'])
                applied = []
                for number, value in enumerate(raw['candidates']):
                    c = validate_candidate(value, evs, day)
                    p = {'action': 'ADD', 'target': None, 'reason': '未找到相似旧记忆'}
                    old = [r for r in self.store.similar(c) if r['id'] != c['id']]
                    if old:
                        context = {'candidate': public_record(c), 'existing': [public_record(r) for r in old]}
                        # Scope the resolver to this exact snapshot. No source manifest is sent.
                        p = self._generate(adapter, RESOLVE_PROMPT, context, lambda v: self._validate_proposal(v, old))
                    provenance = {'model': adapter.identifier, 'promptVersion': PROMPT_VERSION,
                                  'requestId': request['requestId'], 'batchId': batch, 'chunkId': cid}
                    applied.append(MemoryEngine(self.store).apply(c, provenance, p, {r['id'] for r in old}))
                write_json(cached, {'results': applied})
                status['chunks'][cid] = {'state': 'completed', 'execution': 'computed'}
            except (ValueError, OSError, KeyError, TypeError) as exc:
                status['chunks'][cid] = {'state': 'failed', 'error': str(exc)}
            write_json(root / 'status.json', status)
        status['state'] = 'completed' if all(v['state'] == 'completed' for v in status['chunks'].values()) else 'partial'
        write_json(root / 'status.json', status)
        self.store.reindex()
        return status

    @staticmethod
    def _evidence_map(items):
        result = {}
        for e in items:
            if e['id'] in result and e['text'] != result[e['id']]['text']:
                result[e['id']] = {**e, 'text': result[e['id']]['text'] + e['text']}
            else:
                result[e['id']] = e
        return result

    @staticmethod
    def _validate_extracted(value, item):
        if not isinstance(value, dict) or not isinstance(value.get('candidates'), list):
            raise ValueError('模型没有返回 candidates 数组')
        evs = Workflow._evidence_map(item['material']['utterances'])
        for candidate in value['candidates']:
            validate_candidate(candidate, evs, item['material']['date'])

    @staticmethod
    def _validate_proposal(value, old):
        if not isinstance(value, dict) or value.get('action') not in ('ADD', 'NONE', 'UPDATE', 'DELETE', 'UNRESOLVED'):
            raise ValueError('模型变更动作无效')
        if not isinstance(value.get('reason'), str) or not value['reason'].strip():
            raise ValueError('模型变更原因无效')
        target = value.get('target')
        if target is not None and target not in {r['id'] for r in old}:
            raise ValueError('模型目标越界')
        if value['action'] in ('NONE', 'UPDATE', 'DELETE') and not target:
            raise ValueError('模型变更缺少目标')

    @staticmethod
    def _generate(adapter, prompt, material, validator):
        last = None
        for _ in range(2):
            try:
                value = adapter.generate(prompt, material)
                validator(value)
                return value
            except (ValueError, OSError, KeyError, TypeError) as exc:
                last = exc
        raise ValueError(str(last))
