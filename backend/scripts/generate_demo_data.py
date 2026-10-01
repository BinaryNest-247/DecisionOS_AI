from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

random.seed(24)
today = date.today()
industries = ["Manufacturing", "Healthcare", "Retail", "Technology", "Logistics", "Financial Services", "Education", "Hospitality"]
regions = ["West", "North", "South", "East", "Central"]
segments = ["Enterprise", "Mid-market", "Growth", "Small business"]
statuses = ["Active", "Qualified", "New", "Nurture", "Inactive"]
activities = ["Demo requested", "Proposal sent", "Email opened", "Call completed", "Meeting booked", "No response", "Pricing viewed", "Follow-up due"]
rows = []

for index in range(360):
    profile = random.random()
    value = random.randint(150000, 750000) if profile < 0.12 else random.randint(20000, 420000)
    engagement = random.randint(72, 100) if profile < 0.30 else random.randint(8, 88)
    days_ago = random.randint(0, 16) if profile < 0.48 else random.randint(17, 230)
    rows.append({
        "lead_id": f"LD-{index + 1:04d}",
        "company": f"{random.choice(['Northstar', 'Meridian', 'Aster', 'Cobalt', 'Pioneer', 'Vertex', 'Summit', 'Juniper', 'Atlas', 'Keystone'])} {random.choice(['Systems', 'Industries', 'Group', 'Works', 'Holdings', 'Partners'])} {index + 1:03d}",
        "industry": random.choice(industries),
        "lead_value": value,
        "engagement_score": engagement,
        "previous_purchases": random.choices([0, 1, 2, 3, 4, 5, 7], weights=[28, 22, 18, 13, 9, 7, 3])[0],
        "last_contact_date": (today - timedelta(days=days_ago)).isoformat(),
        "lead_status": random.choices(statuses, weights=[33, 21, 19, 15, 12])[0],
        "sales_activity": random.choice(activities),
        "customer_segment": random.choice(segments),
        "region": random.choice(regions),
        "sales_rep": f"Rep {random.choice(['A', 'B', 'C', 'D', 'E', 'F'])}",
    })

for index in (31, 87, 144, 226, 310):
    rows[index]["engagement_score"] = None
for index in (54, 163, 282):
    rows[index]["lead_value"] = None
for index in (16, 203):
    rows[index]["last_contact_date"] = None
for index in (111, 294):
    rows[index]["previous_purchases"] = None

# Preserve repeated source records so the data-quality panel can demonstrate detection.
rows[355] = rows[22].copy()
rows[356] = rows[107].copy()
rows[357] = rows[199].copy()

output = Path(__file__).resolve().parents[2] / "data" / "demo_sales_data.csv"
output.parent.mkdir(parents=True, exist_ok=True)
pd.DataFrame(rows).to_csv(output, index=False)
print(f"Wrote {len(rows)} synthetic records to {output}")