"""DataHealth AI Gold Layer aggregate-only Power BI exporter tests."""
import csv
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from src.export_power_bi import export_aggregates, monthly_series, safe_cell


class ExportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / 'test.db'
        self.out = self.root / 'csv'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.executescript('''
            CREATE TABLE patients(patient_id TEXT);
            CREATE TABLE encounters(encounter_id TEXT, patient_id TEXT, start_time_utc TEXT);
            CREATE TABLE observation_events(observation_id TEXT, category TEXT);
            CREATE TABLE observation_values(observation_id TEXT, component_index INTEGER, measurement_code TEXT, measurement_display TEXT, unit_code TEXT, quality_status TEXT, quality_flags TEXT);
            CREATE TABLE conditions(condition_id TEXT);
            CREATE TABLE diagnostic_reports(report_id TEXT);
            CREATE TABLE medication_requests(medication_request_id TEXT);
            CREATE TABLE clinical_documents(document_id TEXT);
            INSERT INTO patients VALUES ('synthetic-001'), ('synthetic-002');
            INSERT INTO encounters VALUES ('e1','synthetic-001','2026-01-02T09:00:00+00:00'),('e2','synthetic-001','2026-01-06T09:00:00+00:00'),('e3','synthetic-002','2026-03-03T09:00:00+00:00');
            INSERT INTO observation_events VALUES ('o1','vital-signs'), ('o2','laboratory');
            INSERT INTO observation_values VALUES ('o1',0,'8867-4','Heart rate','/min','PASS_STRUCTURAL_CHECKS',NULL),('o2',0,'2345-7','Glucose','mg/dL','REVIEW_REQUIRED','MISSING_CODE');
            INSERT INTO conditions VALUES('c1');
            ''')

    def read(self, file):
        with (self.out/file).open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))

    def test_all_outputs_and_counts(self):
        report = export_aggregates(self.db, self.out)
        self.assertEqual(report['counts']['patients_total'], 2)
        self.assertEqual(report['counts']['flagged_observation_values'], 1)
        self.assertEqual(len(report['files']), 5)
        self.assertEqual(self.read('overview.csv')[0]['encounters_total'], '3')

    def test_empty_month_filled(self):
        export_aggregates(self.db, self.out)
        rows = self.read('monthly_encounters.csv')
        self.assertEqual([r['month_start'] for r in rows], ['2026-01-01','2026-02-01','2026-03-01'])
        self.assertEqual([r['encounter_count'] for r in rows], ['2','0','1'])

    def test_distinct_patient_per_month(self):
        export_aggregates(self.db, self.out)
        self.assertEqual(self.read('monthly_encounters.csv')[0]['monthly_unique_patients'], '1')

    def test_no_patient_identifiers_in_export_files(self):
        export_aggregates(self.db, self.out)
        for f in self.out.glob('*.csv'):
            content = f.read_text(encoding='utf-8-sig')
            self.assertNotIn('synthetic-001', content)
            self.assertNotIn('synthetic-002', content)
            self.assertNotIn('patient_id', content)

    def test_quality_status_and_counts(self):
        export_aggregates(self.db, self.out)
        statuses = {r['quality_status']:r for r in self.read('observation_quality.csv')}
        self.assertEqual(statuses['REVIEW_REQUIRED']['flagged_rows'], '1')

    def test_bad_schema_rejected(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('DROP TABLE conditions')
        with self.assertRaisesRegex(ValueError, 'schema mismatch'):
            export_aggregates(self.db, self.out)

    def test_missing_database_never_created(self):
        missing = self.root/'missing.db'
        with self.assertRaises(FileNotFoundError):
            export_aggregates(missing,self.out)
        self.assertFalse(missing.exists())

    def test_formula_injection_mitigated(self):
        self.assertEqual(safe_cell('=HYPERLINK("http://example.com")'), "'=HYPERLINK(\"http://example.com\")")


if __name__ == '__main__':
    unittest.main()
