# IncuBrix 30-day creator outreach launch kit

Prepared 27 October 2026. This plan uses the verified `leads.csv`; no creator was contacted during the assessment. The reply and meeting rates below are planning assumptions, not observed results.

## Starting segment

Launch gate: at least 2,000 approved creators (the requested target; the brief minimum is 1,000), 25 complete Priority A sequences, passed evidence checks and three completed seed tests. Current approved count: 45. Current country mix: US: 38, GB: 4, CA: 2, AU: 1. Research candidates in review_queue.csv are not eligible for outreach. This plan is prepared; the launch gate is not claimed satisfied.

The opening promise is narrow: turn one verified long-form episode into platform-ready clips, captions and posts, then schedule the variants from one workspace. This matches IncuBrix's published product positioning at https://incubrix.com/.

## Owners and operating rhythm

| Owner | Daily action | Tool | Definition of done |
|---|---|---|---|
| Growth owner | Re-check evidence, approve copy, send and log replies | Evidence dashboard + business mailbox | Every sent row has a same-day check and message ID |
| Product owner | Prepare one content transformation example for positive replies | IncuBrix Creator Studio | Example uses the creator's public episode and is never published without permission |
| Founder/sales owner | Run 15-minute discovery calls and record outcome | Calendar + CRM | Need, current workflow, urgency and next step logged |
| Engineering owner | Refresh and validate the list every Monday | `python -m incubrix_engine run` | Validation report passes; failures are triaged |

## Safe volume and cadence

Week 1 is a monitored pilot: 5 new emails per business day, one follow-up queue, and no automated social DMs. Week 2 may rise to 10 new emails per day only when bounce rate stays below 2%, complaint rate is zero and every opt-out is suppressed within one business day. Weeks 3–4 cap at 15 new emails per day per established mailbox. LinkedIn and Instagram remain manual: at most 5 relevant actions per day per account and only where the creator invites business contact.

Use Day 1 / Day 4 / Day 9 for email. Stop on reply, opt-out, hard bounce or complaint. One creator may have only one active sequence across all channels. Tracking links use first-party UTM parameters; avoid opaque shorteners. Reply events are logged in the CRM against `lead_id`.

## Thirty-day schedule

- Days 1–2: import Priority A, re-check 25 evidence chains, configure suppression fields, authenticate the sending domain and run seed tests on three candidate-owned channels.
- Days 3–5: send 5/day, review every reply manually, and record objections verbatim.
- Week 2: keep the winning segment/message combination; test one variable only (opening hook or CTA). Add 10/day if safety thresholds hold.
- Week 3: expand to the next 50 highest-scoring leads. Product creates a reusable before/after demo for the most common workflow.
- Week 4: send up to 15/day, review channel-level outcomes, refresh the lead evidence and decide whether to scale, revise or stop.

## Targets and decision rules

Planning ranges for 125–200 new contacts: 5–12% total replies, 2–5% positive replies and 1–3% booked meetings. These are hypotheses for a new domain and new message, so the first 25 sends are the baseline. Scale only after at least 50 delivered emails. Pause immediately if hard bounces reach 2%, complaints exceed zero, opt-outs exceed 3%, or channel rules change. A meeting counts only when a calendar event is accepted; a positive reply counts only when the creator asks for a demo, details or later follow-up.

## Stack and budget

- Lead engine, SQLite state, CSV exports and audit dashboard: $0 direct software cost.
- CRM: start with the included CSV and outcome log or an existing company CRM. HubSpot advertises a free CRM (https://www.hubspot.com/products/crm); confirm its limits during account setup. No paid upgrade is assumed.
- IncuBrix: the public site states “Free to start · No card required”; confirm internal limits before launch (https://incubrix.com/).
- Sending mailbox and calendar: use an existing IncuBrix-controlled business account; incremental cost $0 for the pilot. Do not send from the candidate's personal account.
- Hosting: unnecessary for weekly CLI runs. If a review dashboard must be hosted for the assessment, Azure for Students currently provides a $100 credit for eligible students, but Microsoft limits it to education, research, testing and demonstration use; do not use that subscription for IncuBrix commercial production (https://learn.microsoft.com/en-us/azure/education-hub/find-ids).

## Risks and controls

The largest risk is treating a technically deliverable address as consent for irrelevant automation. Control it with one-to-one relevance review, low volume, clear identity and purpose, a plain opt-out, immediate suppression, and no social bulk automation. Other controls: unique stable IDs, exact source URLs, 30-day evidence refresh, no guessed contacts, no sensitive data, role-based access to the CRM, and deletion of rejected raw candidates after the assessment retention window.

## IncuBrix inputs required before launch

An IncuBrix-owned mailbox and calendar, a CRM workspace, an approved sender identity and signature, product demo access, a privacy/retention owner, suppression policy, UTM naming standard, and access to three company-owned test accounts. Legal review should confirm the final copy and lawful basis for each target market before any real outreach.
