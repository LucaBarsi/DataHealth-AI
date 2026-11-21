import tempfile
import unittest
from pathlib import Path
from src.audit_fhir import run_audit


class TestAuditFHIR(unittest.TestCase):
    def test_demo_bundle(self):
        fixture = Path(__file__).resolve().parents[1] / 'data' / 'demo'
        with tempfile.TemporaryDirectory() as temp_dir:
            output = run_audit(fixture, Path(temp_dir))
            self.assertEqual(output['unique_patients'], 1)
            self.assertEqual(output['total_resources'], 5)
            self.assertEqual(output['resource_types']['Observation'], 2)
            self.assertTrue((Path(temp_dir) / 'field_inventory.csv').exists())
            self.assertTrue((Path(temp_dir) / 'eda_report.md').exists())


if __name__ == '__main__':
    unittest.main()
