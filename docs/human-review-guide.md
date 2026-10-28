# Finish the 2,000-lead evidence review

Open `output/Human_Review.xlsx`. Candidates contains real source findings and three message drafts per candidate. Country, commercial and contact fields are research hints until verified. Reviews contains the corresponding editable decisions; nothing starts approved.

1. Open the official site and recent content. Confirm this is the creator, rather than a guest, agency or network. Check dates and English content.
2. Confirm their actual base. Use at least three countries, maximum 60% in one country, and at least 80% in the seven approved markets. The engine conservatively accepts US, CA, GB, IE, AU, NZ and SG only.
3. Verify the creator's own commercial offer and a concrete workflow need. A guest mentioning a course does not establish the creator's commercial activity.
4. Find their published business contact and a different backup route. Copy exact addresses or URLs and a real dated signal showing chosen-channel activity within 60 days. An RSS technical mailbox alone is insufficient.
5. Correct prefilled hints in Reviews. Fill identity, reviewer, dates, rationale and contacts. Use one canonical identity key for the same creator across shows.
6. Supply eight proof URLs and exact short excerpts: identity, country, language, commercial, need, contact, contact activity and backup. Each excerpt is limited to 400 characters. Contact/backup excerpts must contain the exact address or URL; the page's HTML link is acceptable. Copy only what is necessary.
7. Check all three messages. Set decision to Approve only after verification. Leave unresolved rows Pending; mark unsuitable rows Reject. Only Approve rows are imported. To revoke an earlier approval, remove its entry from `config/reviews.json` before rerunning.
8. Save and close Excel, then run:

```powershell
.\Run-Project.ps1 -Action import
.\Run-Project.ps1 -Action run -ReviewedOnly
```

Import validates the complete proposed ledger before saving and creates a backup. The run checks source excerpts, freshness and activity, deduplicates creators and applies country limits. Add `-Refresh` to force live fetching of all cited sources. Failed approvals remain outside the official list; their failure reasons appear in `output/review_queue.json`.

The full research pool remains in `output/research_queue.json` after a reviewed-only run. Your edited Excel file is never overwritten. To create another blank workbook:

```powershell
.\Run-Project.ps1 -Action review -Workbook output/Human_Review_Second_Batch.xlsx
```

The official deliverable is `output/leads.csv`. Your target is 2,000 approved unique creators. The 25 highest-ranked selected creators receive Priority A sequences automatically. The submission workbook expands past 1,000 rows and retains its checking formulas.

Product sign-in/use, real owned-account seed events, two unedited recordings, identity/declaration fields and private sharing links require your participation. Follow `docs/finalization-checklist.md` and `docs/seed-test-runbook.md`. Tests and research counts do not complete those steps.
