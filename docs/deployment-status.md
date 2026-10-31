# Deployment and handoff status

Updated 31 October 2026.

The public overview runs on the user's Azure VM at
http://incubrix-longtail.eastasia.cloudapp.azure.com/ . The `/health.json` endpoint
returns HTTP 200. Nginx serves only the files from `deploy/public/`.

This is a static project overview. The full evidence dashboard and engine jobs
remain local. HTTPS is not configured; the public page contains aggregate counts
and does not accept credentials or review edits. There has been no browser-level
interaction or visual QA in this deployment session.

The local automated suite passes 106 tests; Ruff passes. Four feedparser
deprecation warnings remain. These tests do not establish that 5,000 creators
are qualified or that all live third-party links work.

## Review and data status

`IncuBrix_Manual_Review_5000_USER_ATTESTED.xlsx` records the user's approvals for
the first 4,720 entries in `REVIEW_INDEX`. All eight stored URL/excerpt pairs are
present for one selected creator; the other 4,719 need evidence completion.
Evidence counts are joined by stable creator ID because the workbook's sheets
use different row orders. No rows became engine-qualified from attestation alone.

The private draft ZIP in `dist/` includes this workbook, the code, deployment
assets and the current research artifacts. Generated ZIPs and local credentials
remain excluded from GitHub. Its package manifest marks submission readiness false.

## Still required for the complete assessment

- Fill the missing creator evidence, then import and refresh approved records.
- Generate and complete the final random audit from the qualified output.
- Complete the three owned-account seed tests with screenshots.
- Record five product observations, three opportunities and the two videos.
- Replace credentials disclosed in chat, including the VM password.
