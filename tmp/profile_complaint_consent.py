import csv
from collections import Counter

path = 'consumerComplaints/consumer_complaints.csv'
consent = Counter()
eligible = 0
with open(path, encoding='utf-8-sig', newline='') as handle:
    for row in csv.DictReader(handle):
        narrative = (row.get('consumer_complaint_narrative') or '').strip()
        if narrative:
            value = (row.get('consumer_consent_provided') or '').strip() or '<blank>'
            consent[value] += 1
            if value.lower() in {'consent provided', 'yes'}:
                eligible += 1
print({'narrative_consent_distribution': dict(consent), 'eligible_narratives': eligible})