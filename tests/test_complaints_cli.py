import csv
from pathlib import Path
import tempfile
import unittest

from ingestion.complaints.cli import documents


class ComplaintCliTests(unittest.TestCase):
    def test_documents_resumes_after_a_count_of_consented_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "complaints.csv"
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["consumer_consent_provided", "consumer_complaint_narrative", "complaint_id"])
                writer.writeheader()
                writer.writerows([
                    {"consumer_consent_provided": "Consent provided", "consumer_complaint_narrative": "first", "complaint_id": "1"},
                    {"consumer_consent_provided": "Consent provided", "consumer_complaint_narrative": "second", "complaint_id": "2"},
                ])
            resumed = list(documents(source, skip=1))
        self.assertEqual([document.text for document in resumed], ["second"])


if __name__ == "__main__":
    unittest.main()