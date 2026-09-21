import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

path = Path('consumerComplaints/consumer_complaints.csv')
counts = Counter()
nonempty = Counter()
narrative_lengths = []
dates = []
rows = 0
with path.open(encoding='utf-8-sig', newline='') as handle:
    reader = csv.DictReader(handle)
    headers = reader.fieldnames or []
    for row in reader:
        rows += 1
        for key in headers:
            counts[key] += 1
            if (row.get(key) or '').strip():
                nonempty[key] += 1
        text = (row.get('consumer_complaint_narrative') or '').strip()
        if text:
            narrative_lengths.append(len(text))
        date = (row.get('date_received') or '').strip()
        if date:
            try:
                dates.append(datetime.strptime(date, '%m/%d/%Y').date())
            except ValueError:
                pass
print({'rows': rows, 'columns': headers, 'nonempty': dict(nonempty), 'narrative_count': len(narrative_lengths), 'narrative_length': {'min': min(narrative_lengths) if narrative_lengths else 0, 'max': max(narrative_lengths) if narrative_lengths else 0, 'avg': round(sum(narrative_lengths)/len(narrative_lengths), 1) if narrative_lengths else 0}, 'date_range': [str(min(dates)), str(max(dates))] if dates else None})