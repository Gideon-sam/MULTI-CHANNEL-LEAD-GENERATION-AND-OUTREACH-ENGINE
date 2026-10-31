# Finish the 5,000-creator review

Open **IncuBrix_Manual_Review_5000.xlsx** in the repository root. It contains exactly 5,000
unique-name public creator candidates: 4,177 podcast candidates and 823 YouTube candidates.
Two creators you rejected for missing backup contacts are excluded.

The workbook is an evidence-review pool, not a claim that 5,000 creators already qualify.
Two rows have completed source reviews and still need independent audit; 4,998 require further
evidence review. Missing values remain blank. The engine did not fabricate details.

## Use these sheets

1. **REVIEW_DASHBOARD** — measured counts and the approval rule.
2. **REVIEW_INDEX** — filter by missing checks and prioritize high-coverage rows.
3. **Candidates** — readable discovery facts, activity and public links.
4. **Reviews** — the only sheet where you enter final approval evidence.

For each creator, verify an individual creator identity, an approved country (US, CA, GB, IE,
AU, NZ or SG), mainly English content, activity of 8 items in 30 days or 2 long-form items in
60 days, the creator's own commercial offer, a specific workflow need, an active public business
contact, and a different backup route. Every check needs a working URL and an exact short excerpt.

Set `decision` to **Approve** only when every required value and proof is complete. Use **Reject**
for a known failed gate and leave unresolved rows **Pending**. Save a new copy so the supplied
workbook remains an immutable handoff. Do not contact any creator.

After editing, import the completed copy:

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine review import `
  --workbook "IncuBrix_Manual_Review_5000_COMPLETED.xlsx" `
  --queue "output/runs/20261028T181110372830Z/manual_review_5000_final/manual_review_queue_5000.json" `
  --reviews "config/reviews.json"
```

The import validates the workbook without changing the review ledger if any approval is malformed.
After import, each source must be refreshed and the final dataset deduplicated and country-balanced.
Only the resulting `leads.csv` counts. Generate the fixed-seed random 40-row audit from that final
file, then complete its independent verdicts. The candidate workbook itself is not the final audit.

You must also complete the five IncuBrix product observations, three improvement opportunities,
three owned-account seed tests with screenshots, and two unedited videos. Those facts cannot be
created from public data or inferred by the engine.
