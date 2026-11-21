"""Unit and Gold schema compatibility tests (no real Ollama required)."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import io
import json

from src.clinical_assistant import available_patients, get_patient_context, ollama_chat, main


class ClinicalAssistantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "example.db"
        conn = sqlite3.connect(self.db)
        try:
            conn.executescript("""
                CREATE TABLE patients (patient_id TEXT PRIMARY KEY, full_name TEXT, gender TEXT, birth_date TEXT);
                CREATE VIEW v_patient_overview AS SELECT patient_id,full_name,gender,birth_date FROM patients;
                CREATE TABLE observation_events (observation_id TEXT,patient_id TEXT);
                CREATE TABLE observation_values (observation_id TEXT);
                CREATE TABLE conditions (condition_id TEXT,patient_id TEXT,display TEXT,clinical_status TEXT,verification_status TEXT,onset_datetime_utc TEXT);
                CREATE TABLE medication_requests (medication_request_id TEXT,patient_id TEXT,authored_on_utc TEXT,medication_display TEXT,status TEXT,intent TEXT);
                CREATE TABLE diagnostic_reports (report_id TEXT,patient_id TEXT,effective_datetime_utc TEXT,display TEXT,status TEXT);
                CREATE VIEW v_observations AS
                  SELECT 'p1' AS patient_id, 'o1' AS observation_id, '2026-01-02' AS effective_datetime_utc,
                    '8867-4' AS measurement_code, 'Heart rate' AS measurement_display,
                    82 AS value_numeric, NULL AS value_text, '/min' AS unit_code,
                    'OK' AS quality_status, NULL AS quality_flags, 'vital-signs' AS category;
                INSERT INTO patients VALUES ('p1','Test One','female','2020-01-01');
                INSERT INTO patients VALUES ('p2','Test Two','male','2020-01-01');
                INSERT INTO medication_requests VALUES ('m1','p1','2026-01-02','Example medication','active','order');
            """)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_patient_scoping(self):
        self.assertEqual(len(available_patients(self.db)), 2)
        obs = get_patient_context(self.db, 'p1', 'vitals')
        self.assertEqual(obs['record_count_returned'], 1)
        other = get_patient_context(self.db, 'p2', 'vitals')
        self.assertEqual(other['record_count_returned'], 0)
        with self.assertRaisesRegex(ValueError, 'Unknown patient_id'):
            get_patient_context(self.db, 'no-such-patient', 'overview')

    def test_query_is_read_only_and_allowlisted(self):
        with self.assertRaises(ValueError):
            get_patient_context(self.db, 'p1', "DELETE FROM patients")
        result = get_patient_context(self.db, 'p1', 'medications')
        self.assertEqual(result['records'][0]['medication_display'], 'Example medication')
        self.assertEqual(len(available_patients(self.db)), 2)

    def test_offline_context_cli(self):
        with patch('sys.stdout', new_callable=io.StringIO) as stdout:
            self.assertEqual(main(['--database', str(self.db), 'context', '--patient-id', 'p1', '--topic', 'vitals']), 0)
            self.assertEqual(json.loads(stdout.getvalue())['records'][0]['value_numeric'], 82)

    def test_ollama_payload_is_grounded_and_mocked(self):
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return None
            def read(self): return b'{"message": {"content": "Heart rate is 82 /min."}}'
        # urllib json.load consumes .read from the fake HTTP response
        with patch('src.clinical_assistant.urlopen', return_value=FakeResponse()) as send:
            answer = ollama_chat('Show the heart rate', get_patient_context(self.db, 'p1', 'vitals'))
            self.assertIn('82', answer)
            req = send.call_args.args[0]
            payload = json.loads(req.data)
            self.assertEqual(payload['model'], 'qwen3.5:4b')
            self.assertFalse(payload['stream'])
            self.assertIn('o1', payload['messages'][1]['content'])
        with self.assertRaises(ValueError):
            ollama_chat('Question', {}, base_url='https://example.org')


if __name__ == '__main__':
    unittest.main()
