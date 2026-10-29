# Your manual review: one workbook

Open `MANUAL_REVIEW_START.xlsx` in the project root. Do not work in the old audit CSV for
this task. The workbook contains 40 prioritized candidates from the existing 3,590-row pool;
it is not a random audit or a claim that those 40 qualify. No human verdict is prefilled.

1. On **START_HERE**, enter your name in **B10** and actual review date in **B11** as YYYY-MM-DD.
2. Open **INDEX** and click **OPEN FORM** for the first creator. Start with five creators.
3. On the creator's form, check/correct the yellow values in column B. Open the official
   site/profile/feed links. These facts and evidence excerpts are hints, not approved facts.
4. Scroll to the checks. Column C contains the evidence URL; D contains its exact excerpt;
   E is the engine's fetch date. In **F**, select **Pass**, **Fail**, or **Unsure**. Put your
   correction/reason in **G**. Source warnings are supplied there where available.
5. For missing proof, add a working source URL in C and copy the relevant exact words into D
   (up to 400 characters). Do not replace an excerpt with your opinion. If no proof can be
   found, mark Unsure; a known disqualifier is Fail. No need to contact anyone.
6. Set **B16** to **Approve** only when every check is Pass and all required values/proofs
   are present. Otherwise use **Pending** or **Reject** and explain in the rationale.
7. Save as **.xlsx**, keeping sheet names and stable IDs. Tell me when the first five are
   ready. Leave the rest Pending; you do not have to finish all 40 before returning it.

## What qualifies a creator

| Requirement | What you inspect |
|---|---|
| Real creator | A podcaster, video creator or expert who publishes content; verify their name, official profile, stable ID and canonical identity. Exclude agencies, publications, generic brands, directories and fan accounts. |
| Country | Public evidence locating that creator. Apple storefront, audience location and a guest's bio do not establish it. Current engine-approved countries: US, CA, GB, IE, AU, NZ, SG. |
| English | Their recent content is mainly English. |
| Activity | **8 items in the last 30 days OR 2 long-form items in the last 60 days.** Inspect the ACTIVITY sheet, dates, durations and linked content. |
| Commercial | The creator's own sponsorship, product, service, course, membership, affiliate offer or similar. A guest's offer is not sufficient. |
| IncuBrix need | Specific evidence of a creation, editing, captioning, repurposing, publishing, consistency, backlog or team-workflow need. Explain supported inferences; do not invent dissatisfaction. |
| Primary contact | A real public business email/handle/contact URL belonging to the creator, with evidence it was active within 60 days. Email is optional. A feed-owner mailbox alone does not establish business purpose or activity. |
| Backup contact | A second usable public contact route, different from the primary one. |
| Personalization | The supplied first-message draft names a specific recent piece, identifies the independent sender and includes opt-out. Do not send it. |
| Completeness/uniqueness | Same creator across the evidence; flag possible duplicate shows/profiles. The engine rechecks required fields and duplicates across the final dataset. |
| Freshness/working links | Evidence checked within 30 days; links reach relevant public content. A login screen, 404 or unrelated redirect is not a working proof page. |

The PDF does not specify a numeric minimum duration for long-form. The current engine uses
10 minutes as its operational convention. Flag an ambiguous shorter-format case in your notes
rather than changing its duration or assuming it passes. Do not change qualification gates.

Country mix is a **dataset-level** check: at least 80% approved markets, at least three
countries and no country above 60%. It cannot be approved by checking one creator.
Followers/subscriber counts are optional and may remain blank. Required evidence fields cannot
be removed just because they are blank.

## After your review

I will read your corrections, prepare the existing import format, import only complete approvals,
re-fetch sources and rerun the engine checks. Your review does not automatically approve other
records or establish a random-audit pass rate. The 5,000-qualified target remains outstanding.

Maintainer commands after the user returns the workbook (not needed by the reviewer):

```powershell
.\.venv\Scripts\python.exe -m incubrix_engine.manual_forms convert --input MANUAL_REVIEW_START.xlsx --out output/manual_review_completed.xlsx
.\.venv\Scripts\python.exe -m incubrix_engine review import --workbook output/manual_review_completed.xlsx --queue output/runs/20261028T181110372830Z/auto_enriched_20261029/auto_enriched_queue.json --reviews config/reviews.json
```

Conversion leaves the live review ledger unchanged; it rejects incomplete approvals and changed
identities. The subsequent source recheck is mandatory before any newly approved row counts.
