# 3,000-lead evidence review

The current expansion contains **3,590 unique podcast candidates**. None were silently promoted:
every row remains unqualified until its evidence is manually approved and re-fetched by the
engine. The eight batch workbooks are optional; the master workbook contains the same rows.

## Open this one file

`output/runs/20261028T181110372830Z/expanded_review_3000/Manual_Review_Master.xlsx`

Use the `Candidates` sheet to open discovery links. Enter decisions only in the `Reviews` sheet.
Do not rename columns, change stable IDs, or approve a row merely to reach the target.

For every row marked `Approve`, complete all of these literal values:

1. Your name, review date/time, rationale, corrected creator name and approved country.
2. A canonical official creator URL that identifies the same person across shows.
3. One active business contact and a different backup contact route.
4. A dated public signal proving the primary contact was active within 60 days.
5. The creator's concrete content-workflow need.
6. URL plus an exact excerpt for identity, country, English language, commercial activity,
   need, contact, contact activity and backup contact.

Mark `Reject` when any gate fails and leave `Pending` when evidence is unresolved. A storefront,
RSS-owner email, directory page, guest bio or search-result snippet is not sufficient proof.

To reach 3,000, at least 3,000 candidates must independently pass. The final mix must include at
least three approved countries and no country may exceed 1,800 of the 3,000 rows. Because the
pool is only 590 above target, review every row; the outcome cannot be known in advance.

## Import the completed workbook

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine review import `
  --workbook "output/runs/20261028T181110372830Z/expanded_review_3000/Manual_Review_Master.xlsx" `
  --queue "output/runs/20261028T181110372830Z/expanded_review_3000/expanded_review_queue.json" `
  --reviews "config/reviews.json"
```

The import rejects malformed approvals without changing the review ledger.

## Re-fetch every approved source and build the 3,000-target output

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine run --source apple `
  --config "config/review_recheck_3000.json" `
  --input "output/runs/20261028T181110372830Z/expanded_review_3000/expanded_input.csv" `
  --reviewed-only --refresh
```

The recheck writes to `output_reviewed_3000`. It may exit with code 2 when fewer than 3,000 rows
survive; that is a failed submission gate, not permission to weaken the rules.

