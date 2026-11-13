"""Evidence-overlap preview only; never equates statements or writes memory."""
from .evidence import digest


def compare_candidates(records, facts, reviews=None):
    if not isinstance(records,list) or not isinstance(facts,list):
        raise ValueError('候选与功能事实须为数组')
    old_ids=[r['id'] for r in records];new_ids=[f['id'] for f in facts]
    if len(set(old_ids))!=len(old_ids) or len(set(new_ids))!=len(new_ids):
        raise ValueError('候选或事实编号重复')
    old_evidence={e['id'] for r in records for e in r['evidence']}
    index={};identities={}
    for record in records+facts:
        if not isinstance(record.get('evidence'),list) or not record['evidence']:
            raise ValueError('候选或事实缺少证据')
        for e in record['evidence']:
            identity=(e.get('sourceSHA256'),e.get('startOffsetSeconds'),e.get('endOffsetSeconds'))
            if e['id'] in identities and identities[e['id']]!=identity:
                raise ValueError('同一证据编号的来源或偏移冲突')
            identities[e['id']]=identity
    for fact in facts:
        for e in fact['evidence']:index.setdefault(e['id'],set()).add(fact['id'])
    review_map={}
    if reviews is not None:
        if not isinstance(reviews,list):raise ValueError('复核建议须为数组')
        for review in reviews:
            key=review['memoryId']
            if key not in set(old_ids) or key in review_map:raise ValueError('复核候选未知或重复')
            review_map[key]=review
    rows=[]
    for record in records:
        refs={e['id'] for e in record['evidence']};linked=refs&set(index)
        related=set().union(*(index.get(key,set()) for key in refs))
        review=review_map.get(record['id'])
        if review and review.get('sourceRevisionSHA256')!=digest(record):
            raise ValueError('复核建议的源修订已过期')
        rows.append({'memoryId':record['id'],'date':record['date'],'originalContent':record['content'],
                     'status':record['status'],'revision':record.get('revision'),
                     'sourceEvidenceIds':sorted(refs),'linkedEvidenceIds':sorted(linked),
                     'unlinkedEvidenceIds':sorted(refs-linked),'relatedFactIds':sorted(related),
                     'evidenceMatch':'all_source_evidence_linked' if refs==linked else ('some_source_evidence_linked' if linked else 'no_source_evidence_linked'),
                     'semanticEquivalence':'not_inferred_from_evidence_overlap',
                     'reviewDecision':review.get('decision') if review else None,
                     'proposedContent':review.get('proposedContent') if review else None,
                     'applied':False})
    additional=[f['id'] for f in facts if not ({e['id'] for e in f['evidence']}&old_evidence)]
    return {'schemaVersion':1,'memoryCandidates':len(records),'functionalFacts':len(facts),
            'candidateEvidenceMatches':{label:sum(r['evidenceMatch']==label for r in rows) for label in ['all_source_evidence_linked','some_source_evidence_linked','no_source_evidence_linked']},
            'functionalFactsWithoutOldEvidence':additional,'rows':rows,
            'boundary':'只预览证据关联；同原句可有不同含义，不能推断同义、覆盖正确或直接合并。未写入、更正、确认或撤销任何记忆。'}
