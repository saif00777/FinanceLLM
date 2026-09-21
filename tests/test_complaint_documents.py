import unittest

from ingestion.complaints.documents import build_document, redact_text


class ComplaintDocumentTests(unittest.TestCase):
    def test_redact_text_removes_direct_identifiers(self):
        text = redact_text("Email a@b.com or call 555-123-4567. SSN 123-45-6789.")
        self.assertNotIn("a@b.com", text)
        self.assertNotIn("555-123-4567", text)
        self.assertNotIn("123-45-6789", text)

    def test_document_uses_consented_narrative_and_excludes_zip_and_raw_id(self):
        row = {"consumer_consent_provided": "Consent provided", "consumer_complaint_narrative": "Account 1234567890 was charged.", "complaint_id": "42", "zipcode": "90210", "product": "Mortgage", "sub_product": "Other", "issue": "Billing", "company": "Example", "state": "CA", "date_received": "08/30/2013"}
        document = build_document(row)
        self.assertIsNotNone(document)
        self.assertNotIn("90210", document.text)
        self.assertNotIn("42", document.payload.values())
        self.assertEqual(document.payload["received_year"], 2013)

if __name__ == "__main__": unittest.main()