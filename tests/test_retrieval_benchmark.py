"""Phase 17.1 benchmark tests: no hosted API or model download required."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from cloud_demo.demo_backend import load_fixtures
from cloud_demo.retrieval_benchmark import (
    evaluate_method, lexical_rank, method_summary, retrieval_metrics,
    run_benchmark, validate_queries, write_reports,
)
from cloud_demo.semantic_retrieval import note_corpus

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'cloud_demo' / 'benchmark_fixtures.json'
QUERIES = ROOT / 'cloud_demo' / 'benchmark_queries.json'


class FakeEmbedder:
    """Deterministic tiny vectors only to exercise semantic benchmark path."""
    def embed(self, texts):
        for text in texts:
            text = text.lower()
            yield [1.0 if 'appointment' in text or 'visit' in text else 0.0,
                   1.0 if 'specimen' in text or 'laboratory' in text else 0.0,
                   1.0 if 'medication' in text or 'drug' in text else 0.0,
                   0.5]


class RetrievalBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = load_fixtures(FIXTURE)
        cls.docs = note_corpus(cls.fixtures)
        cls.qdata = json.loads(QUERIES.read_text(encoding='utf-8'))

    def test_has_four_fictional_patients_and_32_notes(self):
        self.assertEqual(len(self.fixtures['patients']), 4)
        self.assertEqual(len(self.docs), 32)
        self.assertTrue(all(d['patient_id'].startswith('DEMO-P') for d in self.docs))

    def test_gold_labels_valid_and_28_queries(self):
        self.assertEqual(len(validate_queries(self.qdata, self.docs)), 28)

    def test_gold_labels_no_cross_patient_references(self):
        owned = {(d['patient_id'], d['document_id']) for d in self.docs}
        self.assertTrue(all((q['patient_id'], did) in owned
                            for q in self.qdata['queries'] for did in q['relevant_document_ids']))

    def test_missing_gold_doc_rejected(self):
        bad = {'synthetic_only':True,'queries':[{'query_id':'Q1','patient_id':'DEMO-P001',
               'question':'test', 'relevant_document_ids':['DEMO-D401']}]}
        with self.assertRaises(ValueError):validate_queries(bad, self.docs)

    def test_missing_synthetic_marker_rejected(self):
        with self.assertRaises(ValueError):validate_queries({'queries':self.qdata['queries']},self.docs)

    def test_duplicate_query_id_rejected(self):
        q = dict(self.qdata['queries'][0]); q2 = dict(self.qdata['queries'][1]);q2['query_id']=q['query_id']
        with self.assertRaises(ValueError):validate_queries({'synthetic_only':True,'queries':[q,q2]},self.docs)

    def test_duplicate_gold_id_rejected(self):
        q = dict(self.qdata['queries'][0]);q['relevant_document_ids']=['DEMO-D101','DEMO-D101']
        with self.assertRaises(ValueError):validate_queries({'synthetic_only':True,'queries':[q]},self.docs)

    def test_lexical_results_never_cross_patients(self):
        doc_owner={d['document_id']:d['patient_id'] for d in self.docs}
        for q in self.qdata['queries']:
            results=lexical_rank(self.docs,q['patient_id'],q['question'],3)
            self.assertTrue(results)
            self.assertTrue(all(doc_owner[did]==q['patient_id'] for did in results))

    def test_lexical_top_k_bounds(self):
        for k in (0,11):
            with self.assertRaises(ValueError):lexical_rank(self.docs,'DEMO-P001','test',k)

    def test_recall_and_mrr_formula(self):
        vals=retrieval_metrics(['a','b','c'],['b'])
        self.assertEqual(vals['recall_at_1'],0)
        self.assertEqual(vals['recall_at_3'],1)
        self.assertEqual(vals['reciprocal_rank_at_3'],0.5)

    def test_no_hit_scores_zero(self):
        self.assertEqual(retrieval_metrics(['a','b'],['c'])['reciprocal_rank_at_3'],0)

    def test_multi_relevant_recall(self):
        self.assertEqual(retrieval_metrics(['a','b'],['a','c'])['recall_at_3'],0.5)

    def test_duplicate_retrieved_rejected(self):
        with self.assertRaises(ValueError):retrieval_metrics(['a','a'],['a'])

    def test_lexical_cli_data_are_real_scores(self):
        summary, rows=run_benchmark(FIXTURE,QUERIES,mode='lexical')
        self.assertEqual(len(rows),28)
        self.assertEqual(list(summary['methods']),['lexical_keywords'])
        self.assertIsNone(summary['semantic_model'])
        self.assertIsNone(summary['semantic_index_build_seconds'])
        self.assertGreaterEqual(summary['methods']['lexical_keywords']['recall_at_1'],0)
        self.assertLessEqual(summary['methods']['lexical_keywords']['recall_at_3'],1)

    def test_semantic_with_fake_embedder_does_not_download(self):
        summary, rows=run_benchmark(FIXTURE,QUERIES,mode='semantic',semantic_embedder=FakeEmbedder())
        self.assertEqual(len(rows),28)
        self.assertIn('semantic_vector_cosine',summary['methods'])
        self.assertNotIn('lexical_keywords',summary['methods'])
        self.assertTrue(all(r['method']=='semantic_vector_cosine' for r in rows))

    def test_both_modes_have_same_query_count(self):
        summary, rows=run_benchmark(FIXTURE,QUERIES,mode='both',semantic_embedder=FakeEmbedder())
        self.assertEqual(len(rows),56)
        self.assertEqual(summary['methods']['lexical_keywords']['queries'],28)
        self.assertEqual(summary['methods']['semantic_vector_cosine']['queries'],28)

    def test_summary_averages(self):
        rows=[{'latency_ms':1,'recall_at_1':0,'recall_at_3':1,'reciprocal_rank_at_3':0.5},
              {'latency_ms':3,'recall_at_1':1,'recall_at_3':1,'reciprocal_rank_at_3':1}]
        s=method_summary(rows)
        self.assertEqual(s['recall_at_1'],0.5)
        self.assertEqual(s['mrr_at_3'],0.75)
        self.assertEqual(s['median_query_latency_ms'],2)

    def test_report_files_present_and_parseable(self):
        summary,rows=run_benchmark(FIXTURE,QUERIES,mode='lexical')
        with tempfile.TemporaryDirectory() as tmp:
            write_reports(Path(tmp),summary,rows)
            for name in ('benchmark_summary.json','benchmark_results.jsonl','benchmark_results.csv','benchmark_report.md'):
                self.assertTrue((Path(tmp)/name).is_file())
            self.assertEqual(json.loads((Path(tmp)/'benchmark_summary.json').read_text())['question_count'],28)
            self.assertEqual(len((Path(tmp)/'benchmark_results.jsonl').read_text().splitlines()),28)

    def test_does_not_modify_production_sample_file(self):
        # Benchmark fixtures are an intentionally separate path.
        self.assertNotEqual(FIXTURE.name,'sample_records.json')


if __name__ == '__main__':
    unittest.main()
