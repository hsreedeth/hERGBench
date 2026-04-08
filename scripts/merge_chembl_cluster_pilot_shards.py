#!/usr/bin/env python3
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve(path: Path) -> Path:
    return (REPO_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def _report_dirs(lead_reports_dir: Path) -> dict[str, Path]:
    if not lead_reports_dir.exists():
        return {}
    out = {}
    for report_json in sorted(lead_reports_dir.rglob("report.json")):
        out[report_json.parent.name] = report_json.parent
    return out


def merge_shards(pilot_root: Path, dry_run: bool = False) -> dict[str, Any]:
    main_lead_reports = pilot_root / "generation" / "run" / "lead_reports"
    main_lead_reports.mkdir(parents=True, exist_ok=True)

    shard_root = pilot_root / "shards"
    shard_dirs = sorted([path for path in shard_root.iterdir() if path.is_dir()])

    copied = []
    skipped_existing = []
    conflicts = []
    ignored_incomplete = []

    for shard_dir in shard_dirs:
        lead_reports_dir = shard_dir / "generation" / "run" / "lead_reports"
        if not lead_reports_dir.exists():
            continue
        for parent_dir in sorted(lead_reports_dir.iterdir()):
            if not parent_dir.is_dir():
                continue
            mol_id = parent_dir.name
            report_json = parent_dir / "report.json"
            if not report_json.exists():
                ignored_incomplete.append(
                    {"shard": shard_dir.name, "mol_id": mol_id, "reason": "missing_report_json"}
                )
                continue

            dst_dir = main_lead_reports / mol_id
            dst_report_json = dst_dir / "report.json"
            if dst_report_json.exists():
                same_report = filecmp.cmp(report_json, dst_report_json, shallow=False)
                if same_report:
                    skipped_existing.append(
                        {"shard": shard_dir.name, "mol_id": mol_id, "action": "already_merged_identical"}
                    )
                    continue
                conflicts.append(
                    {
                        "shard": shard_dir.name,
                        "mol_id": mol_id,
                        "source_report": str(report_json.resolve()),
                        "destination_report": str(dst_report_json.resolve()),
                        "reason": "main_report_differs_from_shard_report",
                    }
                )
                continue

            if not dry_run:
                shutil.copytree(parent_dir, dst_dir)
            copied.append(
                {
                    "shard": shard_dir.name,
                    "mol_id": mol_id,
                    "source_dir": str(parent_dir.resolve()),
                    "destination_dir": str(dst_dir.resolve()),
                }
            )

    main_reports = _report_dirs(main_lead_reports)
    shard_reports = {}
    for shard_dir in shard_dirs:
        shard_reports.update(_report_dirs(shard_dir / "generation" / "run" / "lead_reports"))

    consistency = {
        "main_completed_count": len(main_reports),
        "unique_completed_across_shards": len(shard_reports),
        "main_covers_all_completed_shard_reports": sorted(main_reports) == sorted(shard_reports),
    }

    result = {
        "pilot_root": str(pilot_root.resolve()),
        "dry_run": dry_run,
        "copied": copied,
        "skipped_existing": skipped_existing,
        "ignored_incomplete": ignored_incomplete,
        "conflicts": conflicts,
        "consistency": consistency,
    }
    return result


def _write_outputs(pilot_root: Path, result: dict[str, Any]) -> tuple[Path, Path]:
    logs_dir = pilot_root / "logs"
    summaries_dir = pilot_root / "summaries"
    logs_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = logs_dir / "shard_merge_manifest.json"
    manifest_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# ChEMBL Cluster Pilot Shard Merge",
        "",
        f"- Pilot root: `{pilot_root}`",
        f"- Dry run: `{result['dry_run']}`",
        f"- Copied completed parent dirs: `{len(result['copied'])}`",
        f"- Skipped identical already-merged parent dirs: `{len(result['skipped_existing'])}`",
        f"- Ignored incomplete parent dirs: `{len(result['ignored_incomplete'])}`",
        f"- Conflicts: `{len(result['conflicts'])}`",
        "",
        "## Consistency",
        "",
        f"- Main completed count: `{result['consistency']['main_completed_count']}`",
        f"- Unique completed across shards: `{result['consistency']['unique_completed_across_shards']}`",
        f"- Main covers all completed shard reports: `{result['consistency']['main_covers_all_completed_shard_reports']}`",
        "",
    ]
    if result["copied"]:
        lines.extend(["## Copied", ""])
        for item in result["copied"]:
            lines.append(f"- `{item['mol_id']}` from `{item['shard']}`")
        lines.append("")
    if result["skipped_existing"]:
        lines.extend(["## Skipped Existing", ""])
        for item in result["skipped_existing"]:
            lines.append(f"- `{item['mol_id']}` from `{item['shard']}` already matched main output")
        lines.append("")
    if result["ignored_incomplete"]:
        lines.extend(["## Ignored Incomplete", ""])
        for item in result["ignored_incomplete"]:
            lines.append(f"- `{item['mol_id']}` from `{item['shard']}` ignored because report.json was missing")
        lines.append("")
    if result["conflicts"]:
        lines.extend(["## Conflicts", ""])
        for item in result["conflicts"]:
            lines.append(f"- `{item['mol_id']}` from `{item['shard']}` differed from the main pilot root")
        lines.append("")

    summary_path = summaries_dir / "shard_merge_summary.md"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path, summary_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge completed ChEMBL Cluster pilot shard lead_reports into the main pilot root safely."
    )
    parser.add_argument(
        "--pilot-root",
        type=Path,
        default=Path("reports/lead_opt_literature_audit_chembl/cluster_pilot"),
        help="Pilot root containing shards/ and generation/run/lead_reports.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect shard merge actions without copying anything into the main pilot root.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    pilot_root = _resolve(args.pilot_root)
    result = merge_shards(pilot_root, dry_run=args.dry_run)
    manifest_path, summary_path = _write_outputs(pilot_root, result)

    print("ChEMBL Cluster Pilot Shard Merge")
    print(f"  - pilot_root: {pilot_root}")
    print(f"  - dry_run: {args.dry_run}")
    print(f"  - copied: {len(result['copied'])}")
    print(f"  - skipped_existing: {len(result['skipped_existing'])}")
    print(f"  - ignored_incomplete: {len(result['ignored_incomplete'])}")
    print(f"  - conflicts: {len(result['conflicts'])}")
    print(f"  - main_completed_count: {result['consistency']['main_completed_count']}")
    print(f"  - unique_completed_across_shards: {result['consistency']['unique_completed_across_shards']}")
    print(f"  - main_covers_all_completed_shard_reports: {result['consistency']['main_covers_all_completed_shard_reports']}")
    print(f"  - wrote_manifest: {manifest_path}")
    print(f"  - wrote_summary: {summary_path}")
    return 1 if result["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
