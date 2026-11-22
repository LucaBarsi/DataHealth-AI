"""Offline regression tests for DataHealth AI Phase 16."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cloud_demo.usage_controls import UsagePolicy, SharedProcessBudget, reserve_hosted_call
from cloud_demo.evaluate_cloud import owner_index, sample_cases, run_evaluation, write_reports, main
from cloud_demo.remote_inference import RemoteInferenceError

FIXTURE_PATH = ROOT / 'cloud_demo' / 'sample_records.json'


class UsageTests(unittest.TestCase):
    def test_first_request_is_reserved_and_counted(self):
        session, budget = {}, SharedProcessBudget(max_calls=4)
        accepted, why = reserve_hosted_call(session, budget, now=100)
        self.assertTrue(accepted)
        self.assertEqual(why, 'REQUEST_RESERVED')
        self.assertEqual(session['hosted_calls'], 1)
        self.assertEqual(budget.used(now=100), 1)

    def test_cooldown_does_not_spend_global_request(self):
        session, budget = {}, SharedProcessBudget(max_calls=4)
        reserve_hosted_call(session, budget, now=100)
        accepted, why = reserve_hosted_call(session, budget, now=105)
        self.assertFalse(accepted)
        self.assertEqual(why, 'SESSION_COOLDOWN')
        self.assertEqual(budget.used(now=105), 1)

    def test_session_limit_is_checked_before_global_budget(self):
        policy = UsagePolicy(session_max_calls=1, session_cooldown_seconds=0)
        session, budget = {}, SharedProcessBudget(max_calls=4)
        reserve_hosted_call(session, budget, policy=policy, now=100)
        accepted, why = reserve_hosted_call(session, budget, policy=policy, now=101)
        self.assertFalse(accepted)
        self.assertEqual(why, 'SESSION_CALL_LIMIT')
        self.assertEqual(budget.used(now=101), 1)

    def test_global_limit_across_sessions(self):
        budget = SharedProcessBudget(max_calls=2)
        policy = UsagePolicy(session_cooldown_seconds=0)
        for i in range(2):
            self.assertTrue(reserve_hosted_call({}, budget, policy=policy, now=100+i)[0])
        accepted, why = reserve_hosted_call({}, budget, policy=policy, now=103)
        self.assertFalse(accepted)
        self.assertEqual(why, 'PROCESS_BUDGET_REACHED')

    def test_global_budget_expires(self):
        budget = SharedProcessBudget(max_calls=1, window_seconds=10)
        self.assertTrue(budget.try_reserve(now=0))
        self.assertFalse(budget.try_reserve(now=9.9))
        self.assertTrue(budget.try_reserve(now=10))
        self.assertEqual(budget.used(now=10), 1)

    def test_invalid_limits_rejected(self):
        with self.assertRaises(ValueError):
            UsagePolicy(process_max_calls=0)
        with self.assertRaises(ValueError):
            SharedProcessBudget(max_calls=0)

    def test_threaded_reservations_do_not_exceed_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        budget = SharedProcessBudget(max_calls=4)
        with ThreadPoolExecutor(max_workers=20) as pool:
            granted = list(pool.map(lambda _: budget.try_reserve(now=30), range(30)))
        self.assertEqual(sum(granted), 4)


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))

    def test_six_suggestions_per_patient(self):
        cases = sample_cases(self.fixtures)
        self.assertEqual(len(cases), 24)
        self.assertEqual(len({c['case_id'] for c in cases}), 24)

    def test_single_patient_six_questions(self):
        cases = sample_cases(self.fixtures, patient_id='DEMO-P001', max_cases=6)
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({c['prompt_label'] for c in cases}), 6)

    def test_unknown_patient_rejected(self):
        with self.assertRaises(ValueError):
            sample_cases(self.fixtures, patient_id='DEMO-P999')

    def test_source_ids_not_shared(self):
        index = owner_index(self.fixtures)
        self.assertGreater(len(index), 20)
        self.assertTrue(all(value.startswith('DEMO-P') for value in index.values()))

    def test_duplicate_source_ids_rejected(self):
        duplicate = json.loads(json.dumps(self.fixtures))
        duplicate['patients'][1]['observations'][0]['observation_id'] = duplicate['patients'][0]['observations'][0]['observation_id']
        with self.assertRaises(ValueError):
            owner_index(duplicate)

    def test_offline_no_inference_calls_and_isolation(self):
        with patch('cloud_demo.evaluate_cloud.remote_qwen_answer', side_effect=AssertionError('offline may not call API')):
            summary, results = run_evaluation(fixtures_path=FIXTURE_PATH)
        self.assertEqual(summary['mode'], 'offline')
        self.assertEqual(summary['cases_total'], 24)
        self.assertEqual(summary['patients_included'], 4)
        self.assertEqual(summary['patient_isolation_passed'], 24)
        self.assertEqual(summary['citations_with_unknown_markers'], 0)
        self.assertEqual(summary['hosted_answers_validated'], 0)
        self.assertIsNone(summary['automated_factual_accuracy'])
        self.assertTrue(all(r['status'] == 'EVIDENCE_ONLY' for r in results))

    def test_offline_reports_and_review_template(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            summary, results = run_evaluation(fixtures_path=FIXTURE_PATH, max_cases=2)
            write_reports(out, summary, results)
            self.assertEqual(len((out/'evaluation_results.jsonl').read_text().splitlines()), 2)
            with (out/'manual_review.csv').open(newline='', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                self.assertIn('factual_accuracy', reader.fieldnames)
                self.assertEqual(list(reader), [])  # no LLM answers to review offline

    def test_live_without_credentials_fails_closed(self):
        with self.assertRaises(ValueError):
            run_evaluation(fixtures_path=FIXTURE_PATH, mode='live', max_cases=1)

    def test_live_invalid_marker_falls_back(self):
        with patch('cloud_demo.evaluate_cloud.remote_qwen_answer', return_value='invented [SQL:FAKE]'):
            summary, results = run_evaluation(fixtures_path=FIXTURE_PATH, mode='live', max_cases=1,
                live_settings={'api_base':'https://example.com/v1','api_key':'test','model_id':'qwen'})
        self.assertEqual(summary['hosted_fallbacks'], 1)
        self.assertEqual(results[0]['safe_failure_code'], 'CITATION_CHECK_FAILED')
        self.assertEqual(results[0]['unknown_source_marker_count'], 0) # displayed answer is evidence fallback
        self.assertNotIn('FAKE', results[0]['displayed_answer'])

    def test_live_valid_marker_produces_review_row(self):
        with patch('cloud_demo.evaluate_cloud.remote_qwen_answer', return_value='Heart rate 79 [SQL:DEMO-O003]'):
            summary, results = run_evaluation(fixtures_path=FIXTURE_PATH, mode='live', max_cases=1,
                live_settings={'api_base':'https://example.com/v1','api_key':'test','model_id':'qwen'})
        self.assertEqual(summary['hosted_answers_validated'], 1)
        self.assertTrue(results[0]['exact_citations_pass'])
        with tempfile.TemporaryDirectory() as folder:
            write_reports(Path(folder), summary, results)
            with (Path(folder)/'manual_review.csv').open(newline='', encoding='utf-8') as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['case_id'], 'DEMO-P001:01')

    def test_upstream_failure_safe_code_only(self):
        with patch('cloud_demo.evaluate_cloud.remote_qwen_answer', side_effect=RemoteInferenceError('RATE_LIMITED')):
            summary, results = run_evaluation(fixtures_path=FIXTURE_PATH, mode='live', max_cases=1,
                live_settings={'api_base':'https://example.com/v1','api_key':'SECRET','model_id':'qwen'})
        self.assertEqual(results[0]['safe_failure_code'], 'RATE_LIMITED')
        self.assertNotIn('SECRET', json.dumps(results))

    def test_live_cli_requires_explicit_confirmation(self):
        with self.assertRaises(SystemExit) as err:
            main(['--mode', 'live', '--max-cases', '1'])
        self.assertNotEqual(err.exception.code, 0)

    def test_ui_has_process_budget_and_evidence_only_fallback(self):
        text = (ROOT/'cloud_demo'/'streamlit_app.py').read_text(encoding='utf-8')
        self.assertIn('@st.cache_resource(show_spinner=False)', text)
        self.assertIn('reserve_hosted_call(', text)
        self.assertIn('fallback_reason = usage_reason', text)
        self.assertIn('EVIDENCE_ONLY_FALLBACK', text)
        self.assertIn('st.session_state["messages"]', text)


if __name__ == '__main__':
    unittest.main()
