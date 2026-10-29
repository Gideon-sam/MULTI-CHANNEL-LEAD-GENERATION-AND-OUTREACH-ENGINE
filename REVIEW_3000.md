# 3,000-lead evidence review

## Qualification correction on 29 October

An uncertain podcast author/show name no longer causes immediate rejection. The engine
continues to the official website and retains the creator-identity review flag. This fixes
premature filtering; it does not approve publications, agencies or generic brands. Two
regression cases verify that both a show name and a publication remain pending without
creator-specific approval. The original activity rule remains 8 items in 30 days OR 2
long-form items in 60 days. Optional subscriber counts do not block qualification.

`output_reviewed_3000/leads.csv` contains the separate, newly source-rechecked review output.
Its reviews disclose AI assistance in `config/reviews.json`; they do not represent your
independent audit. Do not combine counts from historical outputs without deduplication and
fresh evidence checks. The older current-run dashboard has not been promoted to a new
submission merely because research has increased.

## Latest automated evidence pass

The full 3,590-candidate source recheck saves its results under:

`output/runs/20261028T181110372830Z/auto_enriched_20261029/`

While it runs, `progress.json` shows the real completed count. After completion, open
`Master_Auto_Enriched.xlsx`. It adds extracted source excerpts, fetch dates, source hashes,
contact-route hints and a coverage sheet to the earlier master. The old master is preserved.

The workbook's `Coverage` sheet lists missing proofs; `Evidence` holds the exact source snippets;
`Link Checks` records fetched and unavailable URLs. All `Reviews` decisions start at `Pending`.
An extracted excerpt still needs checking for creator ownership and meaning. A feed-owner email
or an episode's publishing date does not by itself prove an active business contact.

The final `coverage_report.json` states the achieved coverage and verified additions. The
`integrity/report.json` report, when present, gives the independent source-byte checks. Empty
facts and manual verdicts remain unset. This folder must not be submitted as 3,000 verified leads.

To resume an interrupted run from its saved creator checkpoints, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine.bulk_evidence --input output/runs/20261028T181110372830Z/expanded_review_3000/expanded_input.csv --config config/review_recheck_3000.json --out output/runs/20261028T181110372830Z/auto_enriched_20261029 --refresh --resume
```

Resume requires the same input/configuration and checked date. A completed workbook is protected
from overwriting. For a fresh run on a later day, choose a new output directory and omit `--resume`.

For the enriched workbook, import with:

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine review import --workbook output/runs/20261028T181110372830Z/auto_enriched_20261029/Master_Auto_Enriched.xlsx --queue output/runs/20261028T181110372830Z/auto_enriched_20261029/auto_enriched_queue.json --reviews config/reviews.json
```

Then use the reviewed-only recheck command below. The full source gates run again.

## Earlier review workbook

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

