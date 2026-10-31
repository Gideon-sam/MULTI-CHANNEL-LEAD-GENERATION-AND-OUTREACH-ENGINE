# IncuBrix creator outreach evidence engine

Confused by the generated files? Start with [`START_HERE.md`](START_HERE.md).

## Current supported run command

From the project root on Windows with Python 3.12+ installed, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-Submission.ps1
```

This installs the locked dependencies when needed, runs the full tests and lint, executes available production sources, combines their results with the existing qualification rules, and generates audit/outreach/workbook support. Auto mode always uses Apple/publisher RSS and additionally uses YouTube, Podcast Index/publisher RSS and bounded Tavily evidence hints when their environment variables are available. Tavily results are labelled discovery hints and never qualify a row. Credentials may be set in the Windows user environment or in the local Git-ignored `.env`; never commit, log or copy them into an output. Complete outputs are published into a new folder under `output/runs/` so Excel-open files are preserved. `output/CURRENT_RUN.json` points to the latest complete run; open `output/current.html` for its dashboard. A finished operation does not mean the submission gates pass: read that run's `submission_status.json`.

For a local credential file, copy `.env.example` to `.env` and fill it privately. Blank or absent optional credentials simply disable that provider. The launcher also reads the Windows user environment, including variables added after the IDE was opened.

For a quick clean-clone demonstration, use the same command with `-Mode smoke`. This checks four real records, repeats them, refreshes six, and demonstrates one injected HTTP 404 with continued processing. It is a small execution test, not a production acceptance or scale claim. Evidence is under `verification/current/`. `scripts/verify_clean_clone.py` performs that documented command in a new temporary Git clone and saves its measured result.

Inside the current run folder, open `IncuBrix_Submission_Workbook_Review.xlsx`. `all_discovered_inputs.csv` labels every discovery source; discovery rows are not verified leads. `web_evidence_hints.json` contains search leads for manual source checking, not proof. The random sample filename is recorded in `submission_status.json`. See [audit and demo commands](docs/audit-and-demo-guide.md), [candidate checklist](docs/candidate-checklist.md), [seed screenshots](docs/seed-evidence-checklist.md), and [tools/disclosure](docs/tools-and-disclosure.md). Root-level legacy outputs, `output_youtube_smoke/` and `previous_priority_a/` are historical results, not the current production submission. Existing source-only commands below remain available for diagnosis.

An executable Option 1 assessment project: public podcast discovery, activity checks, evidence review, deduplication, country balancing, outreach drafts, a local audit desk, the official workbook, and an owned-account seed scheduler/tracker.

**Status: implementation and real research artifacts; not a completed submission.** Consult `output/validation_report.json` and `output/manifest.json` for actual counts. Discovery records are not verified leads. The brief requires 1,000 fully qualified creators (5,000 for exceptional), 25 Priority A sequences, product use, real three-channel seed evidence and two unedited videos. Missing evidence is never filled with invented details.

**Your requested target is 5,000 approved creators.** Production enforces that target. The current
5,000-row evidence-review workbook is described in
[`MANUAL_REVIEW_5000.md`](MANUAL_REVIEW_5000.md). Candidate rows are not qualified leads;
imported approvals trigger source checks before official lead export.

Windows shortcuts (run from this folder):

```powershell
.\Run-Project.ps1 -Action setup
.\Run-Project.ps1 -Action verify
.\Run-Project.ps1 -Action dashboard
.\Run-Project.ps1 -Action import
.\Run-Project.ps1 -Action run -ReviewedOnly
```

## Install

Python 3.12+ and internet access. The isolated local verification uses Python 3.15. The Python 3.12 Linux image build and non-root smoke test are recorded in `verification/docker-build.md`. Apple/RSS research works without credentials; the additional sources require their named environment variables. Provider billing and quota remain external account facts and are never inferred.

On a network with HTTPS inspection, pass the organization's trusted CA bundle as an ephemeral BuildKit secret; it is used only during dependency installation and is not stored in the image:

```powershell
docker build --secret id=build_ca_bundle,src=C:\path\to\trusted-ca-bundle.pem -t incubrix-growth-engine .
```

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps -e .
```

On Linux/macOS use `.venv/bin/python` in place of `.venv\Scripts\python.exe`. Activate the environment if using the shorter `python` commands below.

## Legacy Apple/RSS-only run command

```powershell
python -m incubrix_engine run --config config/production.json --input inputs/cached_discovery_expanded.csv
```

Exit `0` means the configured lead checks pass. Exit `2` means the run exported its results but submission requirements remain unmet; this is an intentional quality gate. A traceback or another exit code is an operational error. Read the structured log and the validation report.

The live discovery path (omit `--input`) searches the configured niches through Apple's Search API. Actual network requests are spaced at least 3.1 seconds apart for that API, following its approximately 20/minute documented limit. A large uncached discovery run takes time. Public creator pages are fetched only under accessible robots policies; failed or restricted sources remain unavailable. Robots permission is not a substitute for a site's terms.

## Real imported input and refresh

The repository includes `inputs/cached_discovery_expanded.csv`, reconstructed from two rate-limited passes over actual Apple Search API responses collected during this session. Its records are a discovery pool, not a qualified or approved contact list. `cached_discovery.csv` preserves the first pass and `additional_discovery.csv` preserves only new IDs from the targeted pass.

```powershell
python -m incubrix_engine run --config config/preflight.json --input inputs/cached_discovery.csv
python -m incubrix_engine run --config config/preflight.json --input inputs/cached_discovery.csv --refresh
```

Preflight checks the first 500 input records and writes `output_preflight/`. Production checks up to `max_candidates` and writes `output/`. To introduce new input during the technical demo, provide a different CSV with `apple_id,artist_name,collection_name,feed_url,apple_url,genre` and optional `release_date,country_iso2`. The country input is ignored as evidence. Never invent a platform ID or contact.

`--refresh` refetches sources. SQLite uses stable platform-ID upserts; approved creator identity keys, normalized names and contacts are deduplicated before selection. Lead IDs are derived from stable platform IDs so ranking changes do not change CRM identifiers. `checked_date: "today"` makes weekly runs use the current date.

## Qualification and review

```text
Actual API/input records → dated public feed checks → research queue
                                                      ↓
                                 creator-specific review + source checks
                                                      ↓
                              approved rows → dedupe → country mix → leads.csv
```

Automatic checks establish activity: eight distinct dated items in 30 days or two episodes of at least ten minutes in 60 days. Future-dated entries and duplicate title/date pairs do not count. Feed parsing is limited to a 1 MB prefix; it can conservatively miss activity in unusual oldest-first feeds. Site parsing is limited to 512 KB. Per-candidate work has a 90-second deadline.

Country domains, location phrases, feed owner addresses and commercial keywords are **research hints**. In the sample audit, homepage location phrases sometimes described guests; feed-owner addresses sometimes belonged to hosting providers. These cannot automatically establish creator residence or invited business contact.

To approve a candidate, add a source review to `config/reviews.json` using [the review contract](docs/evidence-review.md). It requires creator identity, country, English content, commercial activity, a concrete content-workflow need, public business contact and recent channel activity, plus a real backup contact route. Each claim needs an exact short excerpt and source URL. The engine verifies excerpt presence, source freshness and availability before exporting the row. A reviewer must assess what the excerpt actually means; keyword matching cannot do that reliably.

`leads.csv` contains only approved rows. `review_queue.csv` contains unresolved candidates. It is not safe to rename the queue to the official lead list. There is no code path that fills invented names, email addresses, followers, countries, reply rates or test results.

## Outputs

| Artifact under the configured output directory | Meaning |
|---|---|
| `leads.csv` | Approved rows, exact official 30-column order, UTF-8 BOM |
| `evidence_ledger.csv` | Approved rows plus source provenance and three message touches |
| `review_queue.csv` / `.json` | Real research candidates awaiting review; country/contact values may be hints |
| `rejections.csv` | Excluded candidates and the reason |
| `discovered_inputs.csv` | Actual input set used by the run |
| `validation_report.json` | Machine-checkable acceptance results |
| `run_summary.json` / `manifest.json` | Counts, measured runtime, HTTP statistics, configuration and artifact hashes |
| `audit_dashboard.html` | Searchable local evidence desk, with status filters and per-row details |
| `IncuBrix_Submission_Workbook_Draft.xlsx` | Original workbook layout and formulas; pending claims remain pending |
| `outreach/` | Three channel templates and full sequences for approved Priority A rows |
| `launch-kit.md` | Conditional 30-day operating plan; observed results and planning assumptions are distinguished |

Open the dashboard directly or serve it locally:

```powershell
python -m incubrix_engine serve --port 8080
```

Then open `http://127.0.0.1:8080/audit_dashboard.html`. The server binds to localhost. It is a local review tool, not an authenticated internet application. Keep exports access-controlled. CSV formula-looking strings are escaped; workbook input cells are text, and green template formulas are preserved. Excel/LibreOffice must recalculate workbook formulas; JSON reports do not depend on spreadsheet formula caches.

## Owned-account seed tooling

The `seed` commands provide a real task schedule, first-party click endpoint, manual native-send evidence logging, replies and suppression. They do not send email or social messages. Read [the seed runbook](docs/seed-test-runbook.md). Empty account fields intentionally prevent a pretend seed run.

```powershell
python -m incubrix_engine seed report
```

A unit test of the seed software is not evidence that actual LinkedIn, Instagram or email messages were scheduled or delivered.

## Verification

```powershell
python -m pytest --junitxml=verification/tests.xml
python -m ruff check src tests scripts
```

Tests use isolated, explicitly synthetic `.test` fixtures. They never populate real deliverables. Coverage includes stale-cache provenance, duplicate activity, evidence gates, redirect recovery, local-address blocking, owned-account scheduling, click handling, reply logging and follow-up suppression.

HTTP cache metadata retains the original fetch time. Failed refresh fallback is explicitly degraded and cannot satisfy approval. Request retries and host limits are bounded; public-page robots rules are checked for the final URL too. Local/private literal and resolved addresses are blocked; production hosting should also enforce an outbound network policy to protect against DNS rebinding. Do not expose this local CLI as an unauthenticated URL-fetching service.

Cache bodies use lossless gzip storage. Projects created before this version can preview and then run the verified one-time migration after all engine processes stop: `python scripts/compress_http_cache.py`, followed by `python scripts/compress_http_cache.py --apply`.

## Submission handoff

See [requirements and honest status](docs/requirements-status.md), [candidate finalization](docs/finalization-checklist.md), and [video runbook](docs/video-runbook.md). Product access, actual seed-account events, unedited candidate videos and the declaration require real user participation. No creator was contacted. A local folder exists; a private repository/shared-folder URL is not fabricated.

Azure hosting is not required by the brief. The included Dockerfile supports a later controlled deployment, but no cloud resources were provisioned. Student subscription eligibility and permitted use must be checked before deployment. Keep the dashboard private and use SSH forwarding for an assessment demonstration.

AI disclosure: OpenAI Codex assisted with code, research automation, source inspection, copy and documentation. The candidate must review and be able to explain the implementation. Public API metadata and publisher RSS access do not imply a licence to republish media. The source cache is excluded from the submission package.
