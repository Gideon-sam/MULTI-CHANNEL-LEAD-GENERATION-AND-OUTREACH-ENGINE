# Evidence status: 29 October 2026

The project is a working draft, not a completed 3,000-qualified-lead submission.

## Open these files

1. `output_reviewed_3000/leads.csv`: **2 newly AI-assisted, source-rechecked leads**, Peter
   McCormack and Fiona Killackey. Both passed the unchanged per-lead validation. The run
   fails submission gates for 3,000 leads, three countries and 25 Priority A leads.
2. `output/runs/20261028T181110372830Z/auto_enriched_20261029/Master_Auto_Enriched.xlsx`:
   **3,590 researched candidates**, with source excerpts, fetch dates, hashes and link checks.
   These are research records, not 3,590 qualified creators. Reviews start at Pending;
   the two separately reviewed records are recorded in `config/reviews.json`.
3. `docs/owned-seed-handoff.md`: the instructions for your three owned-account tests.

The historical current-run output has 45 engine-labelled leads with unresolved review proof
gaps. They have not been independently certified here and must not be counted as fully verified
alongside the two new reviews without reconciliation. Historical outputs were preserved.

## Measured research results

Source: `auto_enriched_20261029/coverage_report.json`.

| Measure | Result |
|---|---:|
| Candidates processed | 3,590 |
| Failed candidate processing tasks | 0 |
| Pending research records | 3,579 |
| Rejected research records | 11 |
| Primary contact hints | 3,192 |
| Backup contact hints | 2,032 |
| Country hints | 18 |
| Missing country proof hints | 3,572 |
| Missing recent contact-activity proof hints | 3,581 |
| Automatically approved by bulk research | 0 |

Contact hints still require ownership and business-context checks. These coverage figures do
not establish accuracy. A source returning HTTP 200 does not prove the claims made about it.
The link-check export has 119 HTTP-404 observations; repeated observations are not unique URLs.
Other blocked, unavailable and stale sources remain explicitly flagged.

The resumed invocation reused 3,030 checkpoints and measured 607.21 seconds through coverage
report creation, with 3,907 network requests and 1,013 cache hits. Those figures exclude earlier
interrupted invocations and the final workbook save. Actual billed cost is unmeasured.
The source-byte audit is under `auto_enriched_20261029/integrity_checked/` after completion;
it verifies stored excerpts, not creator suitability. The earlier `integrity/` report is
preserved, but it incorrectly treated Excel's protective apostrophe as evidence text for
258 excerpts. The corrected checker restores a snippet only when the original checkpoint
exactly confirms the exported value; it does not remove genuine mismatches.

## Filtering and verification

Podcast names that fail the person-name heuristic now continue to official-site research and
remain pending. Neither ambiguous show names nor publications are automatically approved.
The activity gate remains 8 items in 30 days OR 2 long-form items in 60 days. Optional subscriber
counts are not required. No qualification threshold was lowered to increase the count.

The full suite passed: **66 tests**. Lint passed. A fresh clone of commit `5795f1d` ran the
README smoke command successfully in **141.75 seconds**, including small-input refresh and
declared simulated-failure recovery. This does not demonstrate 3,000 qualified leads or a
production-scale refresh. See `verification/clean_clone_report.json`.

## Work still required

- Continue collecting and checking creator-specific country, commercial, workflow-need and
  active business-contact evidence to reach the requested 3,000 qualified creators.
- Independently hand-check the audit sample. Audit pass rates remain unset.
- Use IncuBrix and record your **five observations and three opportunities**, with evidence.
  This is the reminder you requested; those observations cannot be invented for you.
- Perform the three owned-account seed tests and capture scheduling, click and reply proof.
  No real creator was contacted. The environment's automatic approval review blocked the
  earlier local schedule/tracker launch as "blocked by policy"; manual steps are in the handoff.
- Record the two unedited videos: product walkthrough (up to five minutes), technical demo
  (up to eight minutes). Complete the declaration and reviewer-access details.

Removing evidence columns or filling blank verdicts would not resolve these gaps.
