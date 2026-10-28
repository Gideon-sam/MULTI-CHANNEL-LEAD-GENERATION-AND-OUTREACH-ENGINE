# Audit and live-review guide

Use output/submission_status.json as the current status. output/all_discovered_inputs.csv contains source-labelled discovery records; it is not a qualified list. Source runs and smoke runs remain separate. output_youtube_smoke and archived previous_priority_a messages are historical artifacts.

## Audit

The current fixed-seed sample filename is in submission_status.json under audit_sample. It selects up to 40 actual rows from leads.csv using seed 2027 and preserves the selected roster. Fewer than 40 leads produces an explicitly incomplete sample; no rows are invented. The full ledger remains evidence_ledger.csv.

Open the sample in Excel. For every PDF check, enter `pass` or `fail` in its my_verdict column; leave unknown checks blank. Fill my_channel_correct and my_contact_correct independently. A blank does not count as a pass. Inspect the public creator identity, real location, English content, activity dates/durations, commercial offer, concrete workflow need, business-contact invitation, contact activity within 60 days, backup business route, personalization, uniqueness and 30-day evidence freshness. Do not infer residence from an Apple storefront or claim a channel page is a business inbox.

Run `.venv\Scripts\python.exe -m incubrix_engine.audit_support score output/ACTUAL_SAMPLE_FILENAME.csv`. It writes audit_results.json. Qualification and contact accuracy stay unset until every corresponding verdict is filled. A changed roster is rejected. The sample result does not replace IncuBrix's own independent audit or make unmet volume/seed requirements pass.

## Trace five records

Use any lead_id from the random sample:

`.venv\Scripts\python.exe -m incubrix_engine.audit_support trace ACTUAL_LEAD_ID`

It prints each ledger URL, stored snippet, fetch date and provenance. Missing snippets/dates stay blank. Automated snippets require verification against the actual page; a publication date is not a fetch date. A source hash establishes which saved item was used, not whether a business claim is true. Never claim to have watched content based only on metadata.

## Broken links

`.venv\Scripts\python.exe -m incubrix_engine.link_health --out output/link_checks.csv`

This checks the official evidence ledger, follows allowed redirects, and records HTTP errors, malformed URLs, stale fallbacks and unavailable/blocked pages separately. HTTP 200 only proves an HTTP response. Open blocked sources manually where allowed, record your verdict and proof path, and update the evidence review with an independently sufficient public source. Do not guess replacement links or bypass a restriction. A report containing your manual edits is never overwritten; choose a new filename for a rerun.

## Technical demonstration

Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-Submission.ps1 -Mode smoke` from a clean clone. It installs dependencies when needed, runs the full tests and lint, then processes four real inputs, repeats them, refreshes six inputs, and injects one declared HTTP 404 while continuing the other records. See verification/current/run_evidence.json and the four logs. The injected outage is a simulation, not a claim that the creator's feed was actually dead. Zero duplicate state rows establishes UPSERT behavior; it is not proof of thousands of verified creators.

In the video: show the command, outputs, recorded counts, sample trace, repeat IDs, two new IDs, zero state duplicates, failure log, continued processing, missing evidence and the next corrective action. Say clearly which claims remain unverified.
