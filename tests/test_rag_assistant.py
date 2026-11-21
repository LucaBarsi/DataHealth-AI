"""Unit tests for Phase 6; no external model download or Chroma install required."""
import csv
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from src import rag_assistant as rag


class FakeCollection:
    def __init__(self, name, metadata):
        self.name, self.metadata, self.rows = name, metadata, {}

    def count(self):
        return len(self.rows)

    def add(self, ids, documents, metadatas, embeddings):
        for id_, text, meta, vec in zip(ids, documents, metadatas, embeddings):
            self.rows[id_] = (text, meta, vec)

    def query(self, query_embeddings, n_results, where, include):
        rows = [(text, meta) for text, meta, vec in self.rows.values()
                if meta['patient_id'] == where['patient_id']][:n_results]
        return {'documents': [[x[0] for x in rows]],
                'metadatas': [[x[1] for x in rows]],
                'distances': [[0.1 for x in rows]]}


class FakeChroma:
    def __init__(self):
        self.collections = {}

    def PersistentClient(self, path):
        return self

    def get_collection(self, name):
        if name not in self.collections:
            raise ValueError('not found')
        return self.collections[name]

    def create_collection(self, name, metadata):
        c = FakeCollection(name, metadata)
        self.collections[name] = c
        return c

    def delete_collection(self, name):
        del self.collections[name]


class RagAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'gold.db'
        conn = sqlite3.connect(self.db)
        conn.executescript('''
            CREATE TABLE patients(patient_id TEXT PRIMARY KEY, full_name TEXT);
            CREATE TABLE clinical_documents(document_id TEXT PRIMARY KEY, patient_id TEXT,
                status TEXT, rag_candidate_status TEXT);
            INSERT INTO patients VALUES('p1','Synthetic Patient One'),('p2','Synthetic Patient Two');
            INSERT INTO clinical_documents VALUES
                ('d1','p1','current','PRELIMINARY_ONLY_NOT_AUTHORIZED'),
                ('d2','p1','superseded','EXCLUDED_PENDING_REVIEW'),
                ('d3','p2','current','PRELIMINARY_ONLY_NOT_AUTHORIZED');
        ''')
        conn.close()
        self.silver = self.root / 'silver'
        self.silver.mkdir()
        self.records = [
            dict(document_id='d1', patient_id='p1', status='current',
                 rag_candidate_status=rag.ELIGIBLE_STATUS, rag_review_flags='',
                 document_type='Clinical note', document_date='2026-07-01',
                 text_content='Patient one reports no complaints. Synthetic visit.'),
            dict(document_id='d2', patient_id='p1', status='superseded',
                 rag_candidate_status='EXCLUDED_PENDING_REVIEW', rag_review_flags='NON_CURRENT_DOCUMENT',
                 document_type='Clinical note', document_date='2026-06-01',
                 text_content='Superseded and not usable.'),
            dict(document_id='d3', patient_id='p2', status='current',
                 rag_candidate_status=rag.ELIGIBLE_STATUS, rag_review_flags='',
                 document_type='Clinical note', document_date='2026-07-01',
                 text_content='Patient two is here for a checkup.'),
        ]
        with (self.silver/'clinical_documents.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=self.records[0].keys())
            w.writeheader(); w.writerows(self.records)
        self.fake = FakeChroma()

    def tearDown(self):
        self.temp.cleanup()

    def test_current_only_and_correct_patient_link(self):
        docs, counts = rag.load_candidates(self.silver, self.db)
        self.assertEqual([d['document_id'] for d in docs], ['d1', 'd3'])
        self.assertEqual(counts['excluded_noncurrent_or_unapproved'], 1)

    def test_missing_gold_reference_excluded(self):
        self.records[0]['patient_id'] = 'p2'  # mismatched to Gold
        with (self.silver/'clinical_documents.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=self.records[0].keys())
            w.writeheader(); w.writerows(self.records)
        docs, counts = rag.load_candidates(self.silver, self.db)
        self.assertEqual([d['document_id'] for d in docs], ['d3'])
        self.assertEqual(counts['excluded_gold_mismatch'], 1)

    def test_patient_scoped_search_and_model_consistency(self):
        with patch.object(rag, '_chroma', return_value=self.fake), patch.object(
                rag, 'embed_texts', side_effect=lambda texts, *_: [[float(len(t))] for t in texts]):
            summary = rag.build_index(self.silver, self.db, self.root/'idx', self.root/'reports',
                                      rag.DEFAULT_EMBED_MODEL, rag.DEFAULT_OLLAMA)
            self.assertEqual(summary['documents_indexed'], 2)
            found = rag.retrieve(self.db, self.root/'idx', 'p1', 'What was recorded?',
                                 rag.DEFAULT_EMBED_MODEL, rag.DEFAULT_OLLAMA)
            self.assertEqual(len(found['passages']), 1)
            self.assertEqual(found['passages'][0]['document_id'], 'd1')
            self.assertEqual(found['passages'][0]['source_marker'], '[DOC:d1#chunk:0]')
            self.assertRaises(ValueError, rag.retrieve, self.db, self.root/'idx',
                              'p1', 'test', 'another-model', rag.DEFAULT_OLLAMA)
            self.assertRaises(ValueError, rag.retrieve, self.db, self.root/'idx',
                              'other-patient', 'test', rag.DEFAULT_EMBED_MODEL, rag.DEFAULT_OLLAMA)

    def test_chunk_split_and_local_endpoint_check(self):
        text = ' '.join(['synthetic'] * 150)
        chunks = rag.chunk_text(text, max_chars=110, overlap=18)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(c) <= 110 for c in chunks))
        self.assertRaises(ValueError, rag._check_local_url, 'https://example.org')

    def test_answer_uses_evidence_markers(self):
        evidence = {'patient': {'patient_id':'p1','full_name':'Synthetic Patient One'},
                    'question': 'Summary?', 'passages':[{'source_marker':'[DOC:d1#chunk:0]',
                       'document_date':'2026-07-01','document_type':'Clinical note','text':'No complaints.'}]}
        with patch.object(rag, '_post_ollama', return_value={'message':{'content':'No complaints [DOC:d1#chunk:0].'}}) as post:
            answer = rag.answer_with_rag(evidence, 'qwen3.5:4b', rag.DEFAULT_OLLAMA)
            self.assertIn('[DOC:d1#chunk:0]', answer)
            self.assertEqual(post.call_args.args[1], '/api/chat')


if __name__ == '__main__':
    unittest.main()
