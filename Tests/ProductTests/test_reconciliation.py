import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory.reconciliation import compare_candidates
from soundlog_memory.evidence import digest

def ev(key):return {'id':key,'quote':'原话','sourceSHA256':'a'*64,'startOffsetSeconds':0,'endOffsetSeconds':1}
class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.old=[{'id':'m1','date':'2026-11-07','content':'旧摘要','status':'candidate','revision':'r1','evidence':[ev('e1'),ev('e2')]}]
        self.facts=[{'id':'f1','evidence':[ev('e1')]}]
    def test_partial_overlap_never_claims_equivalence(self):
        r=compare_candidates(self.old,self.facts)
        self.assertEqual(r['rows'][0]['unlinkedEvidenceIds'],['e2'])
        self.assertEqual(r['rows'][0]['semanticEquivalence'],'not_inferred_from_evidence_overlap')
        self.assertFalse(r['rows'][0]['applied'])
    def test_new_evidence_and_unlinked_candidate(self):
        r=compare_candidates(self.old,[{'id':'f2','evidence':[ev('e3')]}])
        self.assertEqual(r['functionalFactsWithoutOldEvidence'],['f2'])
        self.assertEqual(r['candidateEvidenceMatches']['no_source_evidence_linked'],1)
    def test_shared_id_different_source_rejected(self):
        self.facts[0]['evidence'][0]['sourceSHA256']='b'*64
        with self.assertRaises(ValueError):compare_candidates(self.old,self.facts)
    def test_stale_refinement_rejected(self):
        review={'memoryId':'m1','sourceRevisionSHA256':'old','decision':'propose_refinement','proposedContent':'new'}
        with self.assertRaises(ValueError):compare_candidates(self.old,self.facts,[review])
    def test_valid_refinement_is_preview_and_inputs_unchanged(self):
        before=copy.deepcopy(self.old);review={'memoryId':'m1','sourceRevisionSHA256':digest(self.old[0]),'decision':'propose_refinement','proposedContent':'更保守的摘要'}
        r=compare_candidates(self.old,self.facts,[review]);self.assertEqual(self.old,before)
        self.assertEqual(r['rows'][0]['proposedContent'],'更保守的摘要');self.assertFalse(r['rows'][0]['applied'])
if __name__=='__main__':unittest.main()
