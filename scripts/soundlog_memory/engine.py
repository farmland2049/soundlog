"""Candidate validation, Mem0-style proposals and auditable review transitions."""
import json
import re
import uuid
from datetime import date
from .evidence import canonical, digest, timestamp
from .protocol import PROMPT_VERSION, TYPES, FUNCTION_USES
from .store import normalize, note_text, now, write_json


def optional_text(value, field):
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError(field + ' 必须为非空文字或 null')
    return value


def validate_candidate(candidate, evidence, day):
    if not isinstance(candidate, dict):
        raise ValueError('候选必须为对象')
    c = dict(candidate)
    if 'functionUses' in c:
        uses = c['functionUses']
        if not isinstance(uses, list) or not uses or any(not isinstance(v, str) or v not in FUNCTION_USES for v in uses):
            raise ValueError('functionUses须为有效非空功能数组')
        c['functionUses'] = sorted(set(uses))
    if c.get('type') not in TYPES or not isinstance(c.get('content'), str) or not c['content'].strip():
        raise ValueError('候选类型或内容无效')
    if c.get('assertion') not in ('explicit', 'suggestion', 'negated', 'reported', 'uncertain'):
        raise ValueError('必须声明 assertion')
    if c['type'] in ('todo', 'decision') and c['assertion'] != 'explicit':
        raise ValueError('建议、否定或转述不得作为确定待办/决策')
    refs = c.get('evidence')
    if not isinstance(refs, list) or not refs:
        raise ValueError('候选必须引用原文证据')
    validated, seen = [], set()
    for ref in refs:
        if not isinstance(ref, dict) or ref.get('id') not in evidence:
            raise ValueError('引用不存在的证据')
        ev = evidence[ref['id']]
        quote = ref.get('quote')
        if not isinstance(quote, str) or not quote.strip() or quote not in ev['text']:
            raise ValueError('引文与原始文字不匹配')
        key = (ref['id'], quote)
        if key not in seen:
            validated.append({'id': ev['id'], 'quote': quote, 'sourceFile': ev['sourceFile'],
                              'sourceSHA256': ev['sourceSHA256'], 'start': ev['start'], 'end': ev['end'],
                              'startOffsetSeconds': ev['startOffsetSeconds'], 'endOffsetSeconds': ev['endOffsetSeconds'],
                              'speakers': ev['speakers']})
            seen.add(key)
    # Do not accept arbitrary names/identities invented by a model.
    quoted = '\n'.join(r['quote'] for r in validated)
    speakers = {s for r in validated for s in r['speakers']}
    for field in ('subject', 'responsible'):
        value = optional_text(c.get(field), field)
        if value is not None and value not in quoted and value not in speakers:
            raise ValueError(field + ' 无原话或匿名标签依据')
        c[field] = value
    entities = c.get('entities', [])
    if not isinstance(entities, list) or any(not isinstance(e, str) or not e.strip() or e not in quoted for e in entities):
        raise ValueError('实体名称必须来自引用原话')
    c['entities'] = sorted(set(entities))
    occurred = optional_text(c.get('occurredAt'), 'occurredAt')
    if occurred is not None:
        timestamp(occurred)
        if not any(r['start'] <= occurred <= r['end'] for r in validated):
            raise ValueError('发生时间不在引用片段内；未知请用 null')
    c['occurredAt'] = occurred
    due_text = optional_text(c.get('dueText'), 'dueText')
    due_date = optional_text(c.get('dueDate'), 'dueDate')
    if due_text and due_text not in quoted:
        raise ValueError('期限原话无来源')
    if due_date:
        date.fromisoformat(due_date)
        # v1 conservatively accepts explicit ISO date literals only.
        if not due_text or due_date not in due_text:
            raise ValueError('首版仅接受原话包含明确 YYYY-MM-DD 的期限日期；其他保留 dueText')
    c.update(evidence=validated, dueText=due_text, dueDate=due_date, date=day)
    # Stable identity distinguishes dates, speakers and evidence spans (repeated events).
    identity = {k: c.get(k) for k in ('type', 'date', 'subject', 'responsible', 'assertion', 'occurredAt', 'dueText', 'dueDate')}
    identity['content'] = normalize(c['content'])
    identity['evidenceIDs'] = sorted({r['id'] for r in validated})
    c['id'] = 'mem-' + digest(identity)[:24]
    result = {k: c[k] for k in ('id', 'date', 'type', 'content', 'assertion', 'occurredAt', 'subject', 'responsible',
                              'dueText', 'dueDate', 'entities', 'evidence')}
    if 'functionUses' in c:
        result['functionUses'] = c['functionUses']
    return result


def revision_hash(record):
    return digest(record)


def public_record(record):
    result = {k: record.get(k) for k in ('id', 'date', 'type', 'content', 'assertion', 'occurredAt', 'subject',
                                     'responsible', 'dueText', 'dueDate', 'entities', 'evidence', 'status', 'revision')}
    if 'functionUses' in record:
        result['functionUses'] = record['functionUses']
    return result


class MemoryEngine:
    def __init__(self, store):
        self.store = store

    def apply(self, c, provenance, proposal=None, allowed_targets=None):
        records = {r['id']: r for r in self.store.records()}
        # Replay after undo must not silently reapply a previously processed input.
        event_key = digest({'candidate': c, 'provenance': provenance, 'proposal': proposal})
        receipt_rel = '运行/已处理/' + event_key + '.json'
        if self.store.path(receipt_rel).exists():
            return {'state': 'reused', **json.loads(self.store.path(receipt_rel).read_text())}
        requested_proposal = dict(proposal) if proposal else None
        if c['id'] in records and (not proposal or proposal.get('target') in (None, c['id'])):
            proposal = {'action': 'NONE', 'target': c['id'], 'reason': '同一证据及候选的精确重复'}
            allowed_targets = None
        p = proposal or {'action': 'UNRESOLVED', 'target': None, 'reason': '尚未进行语义比对'}
        action = p.get('action')
        target = p.get('target')
        if action not in ('ADD', 'NONE', 'UPDATE', 'DELETE', 'UNRESOLVED'):
            raise ValueError('未知变更动作')
        reason = p.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('变更建议必须包含原因')
        if target is not None and (target not in records or (allowed_targets is not None and target not in allowed_targets)):
            raise ValueError('变更目标未在提供的旧记忆中')
        if action in ('NONE', 'UPDATE', 'DELETE') and not target:
            raise ValueError('变更缺少目标')
        if target and records[target]['lifecycle'] != 'active':
            raise ValueError('目标记忆已失效')
        if action == 'NONE':
            old = records[target]
            if c['date'] != old['date']:
                raise ValueError('跨日期内容不得自动按重复合并')
            if c['type'] != old['type'] or c['subject'] != old['subject']:
                raise ValueError('不同类型或主体不得按重复合并')
            new_speakers = {s for e in c['evidence'] for s in e['speakers']}
            old_speakers = {s for e in old['evidence'] for s in e['speakers']}
            if c['subject'] in (None, '我', '我们') and not (new_speakers & old_speakers):
                if not ({e['id'] for e in c['evidence']} & {e['id'] for e in old['evidence']}):
                    raise ValueError('匿名主体缺少同一说话人依据，不得自动合并')
        files = {}
        result = {'action': action, 'memoryId': c['id']}
        if action == 'NONE':
            old = records[target]
            updated = dict(old)
            if 'functionUses' in old or 'functionUses' in c:
                updated['functionUses'] = sorted(set(old.get('functionUses', []) + c.get('functionUses', [])))
            refs = {(r['id'], r['quote']): r for r in old['evidence'] + c['evidence']}
            updated['evidence'] = list(refs.values())
            updated['provenance'] = old.get('provenance', []) + [provenance]
            updated['revision'] += 1
            updated['updatedAt'] = now()
            if target == c['id'] and requested_proposal and requested_proposal.get('action') in ('ADD', 'UNRESOLVED'):
                updated['resolution'] = {'action': requested_proposal['action'], 'reason': requested_proposal['reason']}
            if c['id'] != target and c['id'] in records:
                duplicate = dict(records[c['id']])
                duplicate.update(lifecycle='merged', mergedInto=target, updatedAt=now(), revision=duplicate['revision'] + 1)
                duplicate['resolution'] = {'action': 'NONE', 'reason': reason}
                duplicate['provenance'] = duplicate.get('provenance', []) + [provenance]
                files['笔记/原子记忆/' + c['id'] + '.md'] = note_text(duplicate)
            files['笔记/原子记忆/' + target + '.md'] = note_text(updated)
            result['memoryId'] = target
        elif action in ('UPDATE', 'DELETE'):
            pid = 'change-' + digest({'candidate': c, 'action': action, 'target': target})[:24]
            existing = self.store.path('审核/' + pid + '.json')
            if existing.exists():
                return {'state': 'reused', 'changeId': pid}
            review = {'id': pid, 'state': 'pending', 'action': action, 'target': target,
                      'targetFingerprint': revision_hash(records[target]), 'candidate': c,
                      'reason': reason, 'provenance': provenance, 'createdAt': now()}
            files['审核/' + pid + '.json'] = canonical(review) + '\n'
            result['changeId'] = pid
        else:
            record = {**c, 'status': 'candidate', 'lifecycle': 'active', 'revision': 1,
                      'createdAt': now(), 'updatedAt': now(), 'provenance': [provenance],
                      'possibleConflicts': [target] if target and action == 'UNRESOLVED' else [],
                      'resolution': {'action': action, 'reason': reason}}
            if c['id'] in records:
                previous = records[c['id']]
                record['createdAt'] = previous['createdAt']
                record['revision'] = previous['revision'] + 1
                record['provenance'] = previous.get('provenance', []) + [provenance]
                record['possibleConflicts'] = sorted(set(previous.get('possibleConflicts', []) + record['possibleConflicts']))
            files['笔记/原子记忆/' + c['id'] + '.md'] = note_text(record)
        files[receipt_rel] = canonical(result) + '\n'
        op = self.store.transaction(files, 'candidate:' + action)
        return {'state': 'applied', 'operationId': op, **result}

    def review(self, pid, approve):
        if not re.fullmatch(r'change-[a-f0-9]{24}', pid):
            raise ValueError('无效变更编号')
        rel = '审核/' + pid + '.json'
        p = json.loads(self.store.path(rel).read_text(encoding='utf-8'))
        if p['state'] != 'pending':
            raise ValueError('变更已经审核')
        files = {}
        if approve:
            old = self.store.get(p['target'])
            if revision_hash(old) != p['targetFingerprint']:
                raise ValueError('旧记忆已变化，请重新比较后提交建议')
            old['revision'] += 1
            old['updatedAt'] = now()
            old['lifecycle'] = 'superseded' if p['action'] == 'UPDATE' else 'revoked'
            old['reviewReason'] = p['reason']
            if p['action'] == 'UPDATE':
                new = {**p['candidate'], 'status': 'confirmed', 'lifecycle': 'active', 'revision': 1,
                       'createdAt': now(), 'updatedAt': now(), 'provenance': [p['provenance']],
                       'possibleConflicts': [], 'supersedes': old['id'], 'confirmedAt': now()}
                if new['id'] == old['id']:
                    new['id'] = 'mem-' + digest({'changeId': pid, 'candidate': new['id']})[:24]
                elif self.store.record_path(new['id']).exists():
                    existing = self.store.get(new['id'])
                    if existing['status'] != 'candidate' or existing['lifecycle'] != 'active' or existing['content'] != new['content']:
                        raise ValueError('替代候选已存在且不可替代，请重新比较')
                    new['revision'] = existing['revision'] + 1
                old['supersededBy'] = new['id']
                files['笔记/原子记忆/' + new['id'] + '.md'] = note_text(new)
            files['笔记/原子记忆/' + old['id'] + '.md'] = note_text(old)
        p['state'] = 'approved' if approve else 'rejected'
        p['reviewedAt'] = now()
        files[rel] = canonical(p) + '\n'
        return self.store.transaction(files, 'review:' + p['state'])

    def confirm(self, mid):
        r = self.store.get(mid)
        if r['lifecycle'] != 'active' or r['status'] != 'candidate':
            raise ValueError('仅能确认有效候选')
        r.update(status='confirmed', confirmedAt=now(), updatedAt=now(), revision=r['revision'] + 1)
        return self.store.transaction({'笔记/原子记忆/' + mid + '.md': note_text(r)}, 'confirm')
