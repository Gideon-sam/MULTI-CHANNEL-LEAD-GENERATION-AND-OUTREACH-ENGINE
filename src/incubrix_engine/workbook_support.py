"""Add an evidence index and explicit candidate TODOs to a new review workbook copy."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.comments import Comment

from .files import atomic_destination


def supplement_workbook(source: Path, destination: Path, evidence: dict) -> None:
    workbook = load_workbook(source)
    try:
        start = workbook["00_START"]
        start["B6"] = "[YOUR NAME]"
        start["B16"] = (
            "Used: OpenAI Codex (code, tests, research assistance, documentation and draft copy); "
            "Apple Search API and publisher RSS; YouTube Data API and public YouTube channel feeds; "
            "Google developer documentation; IncuBrix public website; Python, httpx, feedparser, "
            "Beautiful Soup, langdetect, openpyxl, SQLite, pytest, Ruff and Git. "
            "Gemini: NOT USED. No Gemini key or measured Gemini result. "
            "Legacy public research also cited HubSpot and Microsoft documentation. "
            "Exact run artifacts: 05_EVIDENCE_INDEX."
        )
        start["B17"] = None
        start["B17"].comment = Comment(
            "TODO: actual spend from provider billing records; no measured cost supplied.",
            "Evidence review",
        )
        start["B18"] = (
            "AI assisted implementation, deterministic checks, drafting, audit-tool creation and "
            "source inspection. No mass human verification is claimed. Candidate manual work "
            "still required: product use and observations, three opportunities, random audit "
            "verdicts, business-contact validation, three owned-account seed tests, videos and "
            "declaration. Manual time is unmeasured. No real creators contacted."
        )
        for cell in ("F5", "F7", "F9", "F10"):
            start[cell] = None
            start[cell].comment = Comment(
                "TODO: candidate evidence required; not completed by software tests.",
                "Evidence review",
            )
        insight = workbook["01_INSIGHT"]
        for row in (*range(6, 11), *range(14, 17)):
            for column in range(2, 7):
                cell = insight.cell(row, column)
                cell.value = None
                cell.comment = Comment(
                    "TODO: complete from your own authenticated IncuBrix product use; attach evidence.",
                    "Evidence review",
                )
        engine = workbook["03_ENGINE_LAUNCH"]
        engine["C6"] = "../README.md"
        engine["C7"] = "../verification/clean_clone_report.json"
        engine["B7"] = "Yes" if evidence.get("clean_clone_passed") else None
        engine["H7"] = (
            "Small clean-clone execution only; production-scale network run is reported separately."
        )
        engine["C11"] = "../verification/current/run_evidence.json"
        engine["C12"] = "../verification/current/failure_recovery.jsonl"
        engine["C13"] = "../verification/tests.xml"
        engine["B11"] = "Yes" if evidence.get("refresh_demo_passed") else None
        engine["B12"] = "Yes" if evidence.get("failure_demo_passed") else None
        engine["H14"] = "Credentials supplied via process environment; no keys stored in artifacts."
        for row in range(18, 22):
            for column in range(2, 9):
                engine.cell(row, column).value = None
        for index, name in enumerate(
            ("normal", "repeat", "new_input_refresh", "failure_recovery"), 18
        ):
            run = evidence.get("demo", {}).get(name, {})
            if run:
                metrics = run.get("metrics", {})
                for column, key in (
                    (2, "input_size"),
                    (3, "produced"),
                    (4, "rejected"),
                    (5, "duplicates_removed"),
                    (6, "runtime_minutes"),
                ):
                    engine.cell(index, column).value = metrics.get(key)
                engine.cell(index, 8).value = "../" + run["log"]
        for row in range(24, 32):
            engine.cell(
                row, 2
            ).value = (
                "See launch-supplement.md; actual metrics vs planning assumptions are labelled."
            )
        check = workbook["04_SELF_CHECK"]
        links = {
            6: "leads.csv",
            7: "rejection_report.json",
            8: "validation_report.json",
            9: "outreach/segment_channel_sequences.csv",
            10: "outreach/quality_report.json",
            11: "../docs/seed-evidence-checklist.md",
            12: "../verification/clean_clone_report.json",
        }
        for row, link in links.items():
            cell = check.cell(row, 5)
            cell.value = link
            cell.hyperlink = link
        check["C11"] = None
        check["C11"].comment = Comment(
            "TODO: run actual owned-account tests on three channels and link real proof.",
            "Evidence review",
        )
        check["C12"] = "Yes" if evidence.get("clean_clone_passed") else None
        for row in range(17, 21):
            check.cell(row, 2).value = "No"
            check.cell(row, 3).value = None
            check.cell(
                row, 5
            ).value = (
                "Not demonstrated. See submission_status.json and the PDF exceptional requirements."
            )
        for row in range(24, 29):
            check.cell(row, 3).value = None
            check.cell(row, 5).value = "TODO: candidate self-score after reviewing actual evidence."
        sheet = (
            workbook.create_sheet("05_EVIDENCE_INDEX")
            if "05_EVIDENCE_INDEX" not in workbook.sheetnames
            else workbook["05_EVIDENCE_INDEX"]
        )
        sheet.append(["Claim / action", "Evidence file", "Status / TODO"])
        rows = [
            (
                "Official export",
                "leads.csv",
                f"{evidence.get('lead_count', 0)} engine-qualified rows; human audit pending",
            ),
            (
                "Random audit sample",
                evidence.get("audit_sample", ""),
                "TODO: inspect every selected record; leave unreviewed verdicts blank",
            ),
            ("Audit pass rate", "audit_results.json", None),
            ("Channel/contact accuracy", "audit_results.json", None),
            (
                "Working source links",
                "link_checks.csv",
                "HTTP availability is not semantic verification",
            ),
            (
                "Rejections and country mix",
                "rejection_report.json",
                "Computed from official export and source decisions",
            ),
            (
                "Trace any lead",
                "../docs/audit-and-demo-guide.md",
                "Ledger snippets and recorded fetch dates; missing values stay blank",
            ),
            (
                "Outreach quality",
                "outreach/quality_report.json",
                "Review flags before using a draft",
            ),
            (
                "Runtime and actual API calls",
                "runtime_cost_report.json",
                "Measured runtime/calls; billing cost unset",
            ),
            (
                "Clean clone",
                "../verification/clean_clone_report.json",
                "Measured small-run result only",
            ),
            (
                "Product observations and opportunities",
                "../docs/candidate-checklist.md",
                "TODO: five observations and three opportunities from actual product use",
            ),
            ("Owned-account seed proof", "../docs/seed-evidence-checklist.md", None),
            ("Two unedited videos", "../docs/video-runbook.md", "TODO: candidate recordings"),
            (
                "Manual vs AI",
                "../docs/tools-and-disclosure.md",
                "Gemini not used; manual review/time unmeasured",
            ),
        ]
        for label, link, status in rows:
            sheet.append([label, link, status])
            sheet.cell(sheet.max_row, 2).hyperlink = link
            if status is None:
                sheet.cell(sheet.max_row, 3).comment = Comment(
                    "TODO: unmeasured/unperformed; candidate evidence required.", "Evidence review"
                )
        sheet.column_dimensions["A"].width = 38
        sheet.column_dimensions["B"].width = 60
        sheet.column_dimensions["C"].width = 85
        sheet.freeze_panes = "A2"
        with atomic_destination(destination) as temporary:
            workbook.save(temporary)
    finally:
        workbook.close()


def read_optional_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
