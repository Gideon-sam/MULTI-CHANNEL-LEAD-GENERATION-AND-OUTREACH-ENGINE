# IncuBrix reviewer start here

Open **MANUAL_REVIEW_RECORDED_20261030.xlsx**, then **REVIEW_SUMMARY** for your latest decisions.
Read [the next review steps](docs/review-follow-up-20261030.md). Creators 23 and 31 are rejected;
your freshness/link approvals are recorded. Other missing evidence still needs resolution.
The target is **5,000 qualified creators**, which has not been achieved.

## Run

From `D:\Growth`, use the one command in `README.md`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-Submission.ps1
```

The command runs tests and lint before research. It never sends outreach.

## Open only the current run

1. Open `output/current.html` for the current dashboard.
2. Read `output/CURRENT_RUN.json`; its `output_directory` is the only current submission folder.
3. In that folder, read `submission_status.json` first.
4. Open `IncuBrix_Submission_Workbook_Review.xlsx` for the review pack.
5. Use the audit sample named in `submission_status.json` for the independent hand-check.

Root-level output files, `output_youtube_smoke`, and `previous_priority_a` are historical or
source-specific artifacts. Do not submit them as the current result.

## File meanings

| File | Meaning | Action |
|---|---|---|
| `leads.csv` | Engine-qualified rows only | Audit; do not add pending rows |
| `evidence_ledger.csv` | Evidence and provenance for qualified rows | Trace five random leads |
| `review_queue.csv` / `Human_Review.xlsx` | Real candidates with unresolved proofs | Review; not approved leads |
| `web_evidence_hints.json` | Tavily search hints | Fetch and verify; snippets are not proof |
| `rejections.csv` / `rejection_report.json` | Failed gates and grouped counts | Explain rejection logic |
| `outreach/` | Drafts for qualified Priority A leads | Do not send to real creators |
| `tavily_api_report.json` / `runtime_cost_report.json` | Measured local usage | Do not invent billing or quota values |

## Work only the candidate can complete

- Use IncuBrix and record five honest product observations and three opportunities.
- Hand-check the audit sample and enter pass/fail verdicts with corrections.
- Run the three-channel seed test only against accounts you own and capture the required screenshots.
- Record the two unedited videos.
- Complete the declaration and reviewer-access items.

The requested target is 5,000 approved creators, including 250 Priority A sequences. A discovery or review candidate does not count.
Use the real count in `submission_status.json`; never rename a queue to `leads.csv` or fill missing
evidence with assumptions.

For the latest bulk research workbook and progress, open [REVIEW_3000.md](REVIEW_3000.md).
The seed account configuration is local; see [the owned-account seed handoff](docs/owned-seed-handoff.md).
