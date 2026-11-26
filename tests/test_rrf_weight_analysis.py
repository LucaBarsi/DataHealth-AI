"""Phase 17.3 offline tests. Uses deterministic fake vectors; never claims real embedding accuracy."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from cloud_demo.rrf_weight_analysis import (
    SEMANTIC_WEIGHTS, _score, analyze_rankings, build_rankings,
    select_weight, write_reports,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'cloud_demo' / 'benchmark_fixtures.json'
QUERIES = ROOT / 'cloud_demo' / 'benchmark_queries.json'


class FakeEmbedder:
    def embed(self, texts):
        for text in texts:
            value = text.casefold()
            yield [1.0 if 'appointment' in value or 'visit' in value else 0.0,
                   1.0 if 'laboratory' in value or 'blood' in value else 0.0,
                   1.0 if 'medication' in value else 0.0, 0.1]


def cases():
    return [
        {'query_id':'A','patient_id':'DEMO-P001','question':'alpha','gold_ids':['a'],
         'lexical_ids':['b','a','c'],'semantic_ids':['a','c','b']},
        {'query_id':'B','patient_id':'DEMO-P001','question':'beta','gold_ids':['b'],
         'lexical_ids':['b','c','a'],'semantic_ids':['c','b','a']},
        {'query_id':'C','patient_id':'DEMO-P002','question':'gamma','gold_ids':['d'],
         'lexical_ids':['e','d','f'],'semantic_ids':['d','e','f']},
        {'query_id':'D','patient_id':'DEMO-P002','question':'delta','gold_ids':['e'],
         'lexical_ids':['e','d','f'],'semantic_ids':['f','e','d']},
    ]


class RRFWeightUnitTests(unittest.TestCase):
    def test_grid_is_predeclared(self):
        self.assertEqual(SEMANTIC_WEIGHTS, (1.,1.5,2.,3.,4.))

    def test_training_tie_prefers_smaller_weight(self):
        simple = [{'lexical_ids':['a','b'],'semantic_ids':['a','b'],'gold_ids':['a']}]
        self.assertEqual(select_weight(simple), 1.0)

    def test_no_training_data_raises(self):
        with self.assertRaises(ValueError): select_weight([])

    def test_invalid_weights_rejected(self):
        for w in (float('nan'), float('inf'), 0, -1, True):
            with self.subTest(w=w), self.assertRaises(ValueError):
                select_weight(cases(), weights=[w])

    def test_score_bounded(self):
        score = _score(cases(),1.5)
        self.assertTrue(all(0 <= x <= 1 for x in score.values()))

    def test_crossvalidation_covers_each_patient_once(self):
        summary, rows = analyze_rankings(cases())
        self.assertEqual(len(summary['folds']),2)
        self.assertEqual(len(rows),4)
        self.assertEqual({r['query_id'] for r in rows},{'A','B','C','D'})

    def test_no_query_is_in_its_own_training_fold(self):
        s, _ = analyze_rankings(cases())
        for f in s['folds']:
            self.assertEqual(f['training_questions'],2)
            self.assertEqual(f['test_questions'],2)
            self.assertIn(f['chosen_semantic_weight'],SEMANTIC_WEIGHTS)

    def test_summary_metrics_bounded(self):
        summary, _ = analyze_rankings(cases())
        for method, metrics in summary['methods'].items():
            for key,value in metrics.items():
                self.assertTrue(0 <= value <= 1, (method,key,value))

    def test_comparison_totals(self):
        summary,_ = analyze_rankings(cases())
        for comparison in summary['top1_vs_semantic'].values():
            self.assertEqual(comparison['wins']+comparison['ties']+comparison['losses'],4)

    def test_duplicate_query_id_fails(self):
        bad=cases(); bad[2]['query_id']='A'
        with self.assertRaises(ValueError): analyze_rankings(bad)

    def test_patient_scope_mismatch_fails(self):
        bad=cases(); bad[0]['semantic_ids']=['x','y','z']
        with self.assertRaises(ValueError): analyze_rankings(bad)

    def test_missing_relevant_doc_fails(self):
        bad=cases(); bad[0]['gold_ids']=['anotherpatient']
        with self.assertRaises(ValueError): analyze_rankings(bad)

    def test_not_enough_patient_groups(self):
        with self.assertRaises(ValueError): analyze_rankings(cases()[:2])

    def test_no_duplicate_ids_in_outputs(self):
        _, rows=analyze_rankings(cases())
        for row in rows:
            for hits in row['top3'].values():
                self.assertEqual(len(hits),len(set(hits)))

    def test_determinism(self):
        a,b=analyze_rankings(cases())
        c,d=analyze_rankings(cases())
        self.assertEqual(a,c); self.assertEqual(b,d)

    def test_files_generated_and_parseable(self):
        summary,rows=analyze_rankings(cases())
        with tempfile.TemporaryDirectory() as tmp:
            write_reports(Path(tmp),summary,rows)
            for fn in ('weight_analysis_summary.json','weight_analysis_results.jsonl',
                       'weight_analysis_results.csv','weight_analysis_report.md'):
                self.assertTrue((Path(tmp)/fn).is_file())
            self.assertEqual(json.loads((Path(tmp)/'weight_analysis_summary.json').read_text())['question_count'],4)
            with (Path(tmp)/'weight_analysis_results.csv').open(encoding='utf-8',newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))),4)

    def test_retrieval_build_rankings_patient_scoped(self):
        original=FIXTURES.read_bytes()
        cases_,info=build_rankings(FIXTURES,QUERIES,embedder=FakeEmbedder())
        self.assertEqual(len(cases_),28)
        self.assertEqual(len({x['patient_id'] for x in cases_}),4)
        self.assertIn('embedding_model',info)
        self.assertEqual(FIXTURES.read_bytes(),original)
        for x in cases_:
            self.assertEqual(set(x['lexical_ids']),set(x['semantic_ids']))
            self.assertTrue(set(x['gold_ids']).issubset(x['semantic_ids']))

    def test_full_fake_benchmark_report_no_cloud_changes(self):
        cases_,_=build_rankings(FIXTURES,QUERIES,embedder=FakeEmbedder())
        summary, rows=analyze_rankings(cases_)
        self.assertEqual(summary['question_count'],28)
        self.assertEqual(len(summary['folds']),4)
        self.assertEqual(len(rows),28)
        self.assertIn('Do not change public Streamlit',summary['decision'])


if __name__ == '__main__': unittest.main()
