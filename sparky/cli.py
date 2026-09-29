from __future__ import annotations

import argparse
from pathlib import Path

from .crash import analyze_crash, render_crash_report
from .paths import SkyrimPaths, read_active_plugins
from .plugins import assess_load_order


def render_load_order(report) -> str:
    merge = [a for a in report.assessments if a.merge_ready]
    esl = [a for a in report.assessments if a.esl_review_candidate and not a.plugin.is_light]
    automatic_esl = [a for a in report.assessments if a.esl_ready]
    slot_status = (
        "CRITICAL: the standard plugin space is full."
        if report.remaining_full_slots == 0 else
        "WARNING: fewer than 10 standard plugin slots remain."
        if report.remaining_full_slots < 10 else
        "Standard plugin space is currently within the cautious threshold."
    )
    lines = [
        "SPARKY PLUGIN-SPACE REPORT",
        f"Active parsed plugins: {len(report.plugins)}",
        f"Full plugins: {report.full_count} / 254 (includes {len(report.builtin_full)} built-in plugins)",
        f"Light plugins: {report.light_count}",
        f"Remaining full slots: {report.remaining_full_slots}",
        slot_status,
        f"Guarded merge candidates: {len(merge)} (matching master lists required)",
        f"Automatic ESL overlay candidates: {len(automatic_esl)}",
        f"Manual ESL review candidates: {sum(a.esl_status == 'manual_review' for a in report.assessments)}",
        f"Compaction review candidates: {sum(a.esl_status == 'needs_compaction_review' for a in report.assessments)}",
        "",
        "MERGE CANDIDATES (xEdit validation still required)",
    ]
    lines.extend(f"  - {a.plugin.name}: {a.plugin.record_count} records" for a in merge)
    lines.extend(["", "ESL REVIEW CANDIDATES"])
    lines.extend(f"  - {a.plugin.name}: {a.esl_status}, {a.plugin.record_count} records" for a in esl if not a.esl_ready)
    lines.extend(["", "AUTOMATIC ESL OVERLAYS"])
    lines.extend(f"  - {a.plugin.name}" for a in automatic_esl)
    lines.extend(["", "EXCLUSIONS / CAUTIONS"])
    for assessment in report.assessments:
        if assessment.merge_candidate:
            continue
        useful = [reason for reason in assessment.reasons if not reason.startswith("Small, self-contained")]
        if useful:
            lines.append(f"  - {assessment.plugin.name}: {'; '.join(useful)}")
    if report.missing:
        lines.extend(["", "MISSING ACTIVE FILES", *[f"  - {x}" for x in report.missing]])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sparky")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="Analyze the active plugin list without changing it")
    crash_parser = sub.add_parser("crash", help="Translate a Trainwreck crash log")
    crash_parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args(argv)
    paths = SkyrimPaths.detect()
    if args.command == "scan":
        report = assess_load_order(paths.data, read_active_plugins(paths.plugins_txt))
        print(render_load_order(report))
        return 0
    log = args.path or paths.latest_crash()
    if not log:
        parser.error("No Trainwreck crash log was found")
    print(render_crash_report(analyze_crash(log, paths.vortex_mods, read_active_plugins(paths.plugins_txt))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
