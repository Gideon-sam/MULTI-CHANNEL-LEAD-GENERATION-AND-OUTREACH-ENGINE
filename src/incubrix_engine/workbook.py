from __future__ import annotations

from collections import Counter
from copy import copy
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.formula.translate import Translator

from .config import Config
from .files import atomic_destination
from .models import LEAD_COLUMNS, Lead

PUBLIC_OBSERVATIONS = [
    (
        "Public landing page / positioning",
        "The public page presents one workflow from a source recording to clips, captions, voiceovers and posts.",
        "The promise is concrete and outcome-led; authenticated feature testing is still pending because invitation access was not available in this workspace.",
        "https://incubrix.com/",
        "A single-source-to-many-assets promise maps directly to creators with a recent long-form backlog.",
    ),
    (
        "Content insights",
        "The public page says IncuBrix ranks niche trends and content gaps before recording.",
        "This can shorten ideation, but the quality and provenance of recommendations require an authenticated product test.",
        "https://incubrix.com/",
        "An evidence-backed topic preview is a useful acquisition hook for expert-led creators.",
    ),
    (
        "Transcript editing",
        "The public page describes removing video by deleting transcript text and extracting strong moments.",
        "The interaction is easy to explain; export quality, timing and edge cases remain unverified without product access.",
        "https://incubrix.com/",
        "A before/after clip made from a creator's real episode can demonstrate value faster than a feature list.",
    ),
    (
        "Publishing",
        "The public page lists YouTube, Instagram, LinkedIn, Spotify and Bluesky publishing from one screen.",
        "The multi-channel scope supports the outreach promise; account connection and failure recovery remain to be tested in-product.",
        "https://incubrix.com/",
        "Channel consolidation is strongest for creators already publishing long-form on a repeat cadence.",
    ),
    (
        "Roadmap clarity",
        "Cross-platform performance, 100+ languages, brand presets and team workspace are labelled coming soon on the public page.",
        "The labels set expectations clearly; outreach must avoid selling these as available today.",
        "https://incubrix.com/",
        "Accurate availability claims protect trust and prevent sales conversations from creating product debt.",
    ),
]


def build_workbook(
    template: Path,
    destination: Path,
    leads: list[Lead],
    config: Config,
    run_metrics: dict[str, Any],
    *,
    seed_test_passed: bool = False,
) -> None:
    workbook = openpyxl.load_workbook(template)
    try:
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        workbook.calculation.calcMode = "auto"
    except AttributeError:
        pass

    start = workbook["00_START"]
    start["B6"] = config.sender_name
    start["B16"] = (
        "OpenAI Codex (implementation, drafting and sample audit; no blanket review claim); Apple Search API; "
        "publisher-syndicated RSS; IncuBrix public site; Python, httpx, feedparser, openpyxl, "
        "Beautiful Soup, langdetect, SQLite, pytest; HubSpot and Azure public documentation."
    )
    start["B17"] = "$0 direct spend; no paid data or outreach tools used."
    start["B18"] = (
        "AI assisted code and copy drafting. Automated public-source checks produced the candidate "
        "pool; no creator was contacted. Product login test, seed tests, videos, repository upload "
        "and candidate-only identity fields remain manual and are not claimed complete."
    )
    for cell, value in {
        "F5": "No",
        "F6": "Yes" if len(leads) >= 1000 else "No",
        "F7": "No",
        "F8": "Yes",
        "F9": "No",
        "F10": "No",
    }.items():
        start[cell] = value

    insight = workbook["01_INSIGHT"]
    for row_index, observation in enumerate(PUBLIC_OBSERVATIONS, start=6):
        for column_index, value in enumerate(observation, start=2):
            insight.cell(row=row_index, column=column_index, value=value)
    opportunities = [
        (
            "Lead with a verified episode-to-assets preview",
            "output/evidence_ledger.csv + https://incubrix.com/",
            "Turns an abstract platform promise into a creator-specific proof point.",
            "Positive-reply and meeting rate vs. generic copy",
            "25 manually reviewed previews; >=2 positive replies as a planning target",
        ),
        (
            "Own the creator-led podcast wedge first",
            "output/leads.csv (active long-form cadence and commercial evidence)",
            "The source format and publishing cadence closely match the repurposing workflow.",
            "Replies, meetings and activated workspaces by segment",
            "125-200 compliant sends; 5-12% reply hypothesis; measure actual baseline",
        ),
        (
            "Use evidence expiry and suppression as growth infrastructure",
            "output/validation_report.json and launch-kit.md",
            "Higher contact accuracy protects domain reputation and makes weekly scaling repeatable.",
            "Bounce, complaint, opt-out, duplicate and stale-evidence rates",
            "<2% hard bounce; 0 complaints; 0 duplicates; 100% opt-outs suppressed",
        ),
    ]
    for row_index, values in enumerate(opportunities, start=14):
        for column_index, value in enumerate(values, start=2):
            insight.cell(row=row_index, column=column_index, value=value)

    leads_sheet = workbook["02_LEADS"]
    final_row = max(1004, len(leads) + 4)
    if final_row > 1004:
        for row_number in range(1005, final_row + 1):
            for template_cell in leads_sheet[1004]:
                cell = leads_sheet.cell(row_number, template_cell.column)
                cell._style = copy(template_cell._style)
                if template_cell.data_type == "f":
                    cell.value = Translator(
                        template_cell.value, origin=template_cell.coordinate
                    ).translate_formula(cell.coordinate)
            leads_sheet.row_dimensions[row_number].height = leads_sheet.row_dimensions[1004].height
        # Extend absolute duplicate ranges across the complete official list.
        for row in leads_sheet.iter_rows(min_row=5):
            for cell in row:
                if cell.data_type == "f":
                    cell.value = cell.value.replace("$1004", f"${final_row}")
        leads_sheet.auto_filter.ref = f"A4:AD{final_row}"
        for validation in leads_sheet.data_validations.dataValidation:
            validation.sqref = str(validation.sqref).replace("1004", str(final_row))
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f" and "1004" in cell.value:
                        cell.value = cell.value.replace("1004", str(final_row))
    for row_offset, lead in enumerate(leads, start=5):
        row = lead.workbook_row()
        for column_index, column in enumerate(LEAD_COLUMNS, start=1):
            if column in {"duplicate_check", "completeness_check"}:
                continue
            cell = leads_sheet.cell(row=row_offset, column=column_index, value=row[column])
            if isinstance(row[column], str):
                cell.data_type = "s"

    engine = workbook["03_ENGINE_LAUNCH"]
    proof_rows = {
        6: ("Yes", "README.md", "One production command plus documented setup."),
        7: (
            "Yes",
            "verification/docker-build.md; Dockerfile; .github/workflows/ci.yml",
            "Clean Python 3.12 Linux image built; non-root CLI and dependency smoke tests passed.",
        ),
        8: (
            "Yes",
            "src/incubrix_engine/storage.py; validation_report.json",
            "Stable IDs and SQLite UPSERT.",
        ),
        9: ("Yes", "src/incubrix_engine/validation.py", "Hard checks run before export."),
        10: ("Yes", "output/leads.csv", "UTF-8 BOM, official 30-column order."),
        11: (
            "Yes",
            "verification/run_evidence.json; verification/*.jsonl",
            "Same-input rerun and refreshed new-input run completed; stable approved IDs matched.",
        ),
        12: (
            "Yes",
            "logs/run-*.jsonl; tests/test_http_recovery.py",
            "Recovery is tested with an injected network failure; not an actual outage claim.",
        ),
        13: ("Yes", "tests/", "Qualification, dedupe, validation and recovery coverage."),
        14: (
            "Yes",
            ".env.example; .gitignore",
            "No credentials committed; public-data run needs no key.",
        ),
    }
    for row, (done, evidence, note) in proof_rows.items():
        engine.cell(row=row, column=2, value=done)
        engine.cell(row=row, column=3, value=evidence)
        engine.cell(row=row, column=8, value=note)
    normal = [
        run_metrics.get("input_size", 0),
        len(leads),
        run_metrics.get("rejected", 0),
        run_metrics.get("duplicates_removed", 0),
        run_metrics.get("runtime_minutes", 0),
        "$0",
        "logs/run-*.jsonl; run_summary.json",
    ]
    for column, value in enumerate(normal, start=2):
        engine.cell(row=18, column=column, value=value)
    verification_runs = {
        19: (8, 0, 5, 0, 0.08, "$0", "verification/repeat.jsonl; run_evidence.json"),
        20: (
            10,
            0,
            6,
            0,
            0.32,
            "$0",
            "verification/new_input_refresh.jsonl; run_evidence.json",
        ),
        21: (
            "Injected HTTP failures",
            "continued",
            "handled",
            0,
            "<1",
            "$0",
            "verification/tests.xml; tests/test_http_recovery.py",
        ),
    }
    for row, values in verification_runs.items():
        for column, value in enumerate(values, start=2):
            engine.cell(row=row, column=column, value=value)

    launch_values = {
        24: "Creator-led podcasters with reviewed identity, country, activity, commercial, need and business-contact evidence. Research candidates do not count as leads.",
        25: "Use each lead's reviewed best channel. Email, LinkedIn and Instagram templates exist; their suitability requires creator-specific evidence.",
        26: "Growth owner re-checks Priority A, sends 5/day from an IncuBrix mailbox, logs CRM outcomes; product owner prepares episode-to-assets examples.",
        27: "Scale to 10/day then 15/day only if hard bounces stay <2%, complaints remain zero and opt-outs are suppressed same day.",
        28: "$0 incremental pilot: this engine + HubSpot free CRM + existing IncuBrix mailbox; optional paid upgrades require approval.",
        29: "125-200 new contacts; 5-12% reply, 2-5% positive reply, 1-3% meeting planning hypotheses; measure actual baseline before scaling.",
        30: "Risk: irrelevant or non-compliant outreach. Control: same-day evidence check, one-to-one review, low volumes, clear identity/opt-out and global suppression.",
        31: "IncuBrix mailbox/calendar, CRM, approved sender/signature, product demo access, retention owner, suppression policy and 3 company-owned seed accounts.",
    }
    for row, value in launch_values.items():
        engine.cell(row=row, column=2, value=value)

    self_check = workbook["04_SELF_CHECK"]
    countries = Counter(lead.country_iso2 for lead in leads)
    country_pass = (
        len(countries) >= 3
        and sum(countries[c] for c in config.approved_countries) / max(1, len(leads)) >= 0.8
        and max(countries.values(), default=0) / max(1, len(leads)) <= config.max_country_share
    )
    self_check["C6"] = len(leads)
    self_check["E6"] = "output/leads.csv; output/validation_report.json"
    self_check["C7"] = "Yes" if country_pass else "No"
    self_check["E7"] = "output/run_summary.json; output/validation_report.json"
    self_check["C8"] = len(leads) - len({lead.stable_creator_id for lead in leads})
    self_check["E8"] = "output/validation_report.json"
    self_check["C9"] = 3
    self_check["E9"] = "outreach/channel_sequences.md"
    self_check["C10"] = sum(lead.priority == "A" for lead in leads)
    self_check["E10"] = "outreach/priority_a_sequences.csv; outreach/priority_a/"
    self_check["C11"] = "Yes" if seed_test_passed else "No"
    self_check["E11"] = "Pending user-owned 3-channel seed accounts; no result fabricated"
    self_check["C12"] = "Yes"
    self_check["E12"] = "verification/run_evidence.json; verification/*.jsonl"
    for row, achieved, value, evidence in [
        (17, "No", len(leads), "Minimum-quality run only; no 5,000-lead claim"),
        (18, "No", sum(lead.priority == "A" for lead in leads), "Priority A sequences folder"),
        (19, "No", len(leads), "No 5,000-row runtime claim"),
        (20, "No", "No live response data", "Real creators were not contacted, per brief"),
    ]:
        self_check.cell(row=row, column=2, value=achieved)
        self_check.cell(row=row, column=3, value=value)
        self_check.cell(row=row, column=5, value=evidence)

    score_rows = [
        (
            24,
            5,
            "Public product evidence is specific; authenticated product walkthrough is pending.",
        ),
        (
            25,
            31 if len(leads) >= 1000 else 20,
            "Evidence ledger, strict qualification, official-format CSV and personalised Priority A sequences.",
        ),
        (
            26,
            19,
            "One-command cached refresh, UPSERT dedupe, hard validation, recovery tests and auditable logs.",
        ),
        (
            27,
            9,
            "Actionable 30-day launch kit with owners, safe volume, budget, targets and stop rules.",
        ),
        (
            28,
            15,
            "Audit dashboard and runbook support live tracing; actual live review has not occurred.",
        ),
    ]
    for row, _score, reason in score_rows:
        self_check.cell(row=row, column=3, value=None)
        self_check.cell(row=row, column=5, value="Self-score pending candidate review. " + reason)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with atomic_destination(destination) as temporary:
        workbook.save(temporary)
