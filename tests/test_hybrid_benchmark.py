"""Phase 17.2 regression tests. No network, model download or hosted API."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from cloud_demo.hybrid_benchmark import (
    METHODS, _pairwise_deltas, rrf_fuse, run_hybrid_benchmark, write_hybrid_reports,
)
from cloud_demo.demo_backend import load_fixtures
from cloud_demo.semantic_retrieval import note_corpus

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'cloud_demo' / 'benchmark_fixtures.json'
QUERIES = ROOT / 'cloud_demo' / 'benchmark_queries.json'


class OfflineEmbedder:
    """Deterministic fake solely for testing code paths, NOT for metrics claims."""
    def embed(self, texts):
        for value in texts:
            text = value.lower()
            yield [1.0 if 'visit' in text or 'appointment' in text else 0.,
                   1.0 if 'lab' in text or 'specimen' in text else 0.,
                   1.0 if 'drug' in text or 'medication' in text else 0.,
                   .25]


class RRFTests(unittest.TestCase):
    def test_first_document_of_both_ranks_wins(self):
        self.assertEqual(rrf_fuse(['a','b','c'],['a','c','b'])[0], 'a')

    def test_complementary_ranks_can_change_first_choice(self):
        self.assertEqual(rrf_fuse(['a','b','c'],['b','c','a'])[0], 'b')

    def test_deterministic_tie_break(self):
        # Both documents receive exactly the same reciprocal-rank score.
        self.assertEqual(rrf_fuse(['b','a'],['a','b']), ['a','b'])

    def test_equal_weight_scaling_does_not_change_order(self):
        a = rrf_fuse(['x','y','z'],['z','x','y'])
        b = rrf_fuse(['x','y','z'],['z','x','y'],lexical_weight=2.,semantic_weight=2.)
        self.assertEqual(a,b)

    def test_weighted_lexical_can_win(self):
        result = rrf_fuse(['a','b','c'],['c','b','a'],lexical_weight=3.,semantic_weight=1.)
        self.assertEqual(result[0],'a')

    def test_disallow_duplicate_candidates(self):
        with self.assertRaises(ValueError):rrf_fuse(['a','a'], ['a','b'])

    def test_disallow_mismatched_scope(self):
        with self.assertRaises(ValueError):rrf_fuse(['a','b'], ['a','c'])

    def test_disallow_empty_rankings(self):
        with self.assertRaises(ValueError):rrf_fuse([], [])

    def test_disallow_invalid_rrf_constant(self):
        for k in (0, -1, 1.5, True):
            with self.subTest(k=k), self.assertRaises(ValueError):
                rrf_fuse(['a'],['a'],rrf_k=k)

    def test_disallow_invalid_weights(self):
        for weight in (0,-1,float('nan'),float('inf'),True):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                rrf_fuse(['a'],['a'],semantic_weight=weight)


class HybridBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary,cls.rows=run_hybrid_benchmark(FIXTURES,QUERIES,embedder=OfflineEmbedder())

    def test_three_methods_and_84_rows(self):
        self.assertEqual(len(self.rows),84)
        self.assertEqual(tuple(self.summary['methods']),METHODS)
        self.assertEqual(self.summary['question_count'],28)
        self.assertEqual(self.summary['document_count'],32)

    def test_patient_isolation_for_every_result(self):
        owners={d['document_id']:d['patient_id'] for d in note_corpus(load_fixtures(FIXTURES))}
        for row in self.rows:
            for docid in row['retrieved_document_ids']:
                self.assertEqual(owners[docid],row['patient_id'])

    def test_same_queries_and_gold_labels_across_methods(self):
        grouped={}
        for row in self.rows:
            grouped.setdefault(row['query_id'],[]).append(row)
        for group in grouped.values():
            self.assertEqual({r['method'] for r in group},set(METHODS))
            self.assertEqual(len({tuple(r['relevant_document_ids']) for r in group}),1)

    def test_ranking_is_unique_and_at_most_three(self):
        for row in self.rows:
            ids=row['retrieved_document_ids']
            self.assertEqual(len(ids),len(set(ids)))
            self.assertLessEqual(len(ids),3)

    def test_metrics_are_bounded(self):
        for method in METHODS:
            stat=self.summary['methods'][method]
            for metric in ('recall_at_1','recall_at_3','mrr_at_3'):
                self.assertTrue(0.0<=stat[metric]<=1.0)

    def test_defaults_are_explicit_and_not_tuned(self):
        self.assertEqual(self.summary['fusion']['rrf_k'],60)
        self.assertEqual(self.summary['fusion']['lexical_weight'],1.0)
        self.assertEqual(self.summary['fusion']['semantic_weight'],1.0)

    def test_pairwise_case_counts_add_up(self):
        for comp in self.summary['hybrid_top1_comparisons'].values():
            self.assertEqual(comp['hybrid_top1_wins']+comp['hybrid_top1_ties']+comp['hybrid_top1_losses'],28)
            self.assertEqual(len(comp['improved_query_ids']),comp['hybrid_top1_wins'])
            self.assertEqual(len(comp['regressed_query_ids']),comp['hybrid_top1_losses'])

    def test_reports_write_without_mutating_benchmark_fixtures(self):
        before=FIXTURES.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            write_hybrid_reports(out,self.summary,self.rows)
            names=('hybrid_summary.json','hybrid_results.jsonl','hybrid_results.csv','hybrid_report.md')
            self.assertTrue(all((out /name).is_file() for name in names))
            with (out/'hybrid_results.csv').open(encoding='utf-8', newline='') as csv_file:
                rows=list(csv.DictReader(csv_file))
            self.assertEqual(len(rows),84)
            self.assertIn('Individual query analysis',(out/'hybrid_report.md').read_text())
            self.assertEqual(json.loads((out/'hybrid_summary.json').read_text())['question_count'],28)
        self.assertEqual(FIXTURES.read_bytes(),before)

    def test_reject_nonfictional_or_mismatched_labels(self):
        payload=json.loads(QUERIES.read_text(encoding='utf-8'))
        payload['synthetic_only']=False
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad_queries.json'
            path.write_text(json.dumps(payload),encoding='utf-8')
            with self.assertRaises(ValueError):
                run_hybrid_benchmark(FIXTURES,path,embedder=OfflineEmbedder())


if __name__ == '__main__':
    unittest.main()
