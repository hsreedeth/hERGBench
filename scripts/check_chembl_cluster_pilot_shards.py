#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve(path: Path) -> Path:
    return (REPO_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def _panel_ids(panel_path: Path) -> list[str]:
    if not panel_path.exists():
        return []
    df = pd.read_csv(panel_path)
    if "mol_id" not in df.columns:
        raise ValueError(f"Panel file missing mol_id column: {panel_path}")
    return df["mol_id"].astype(str).tolist()


def _completed_reports(lead_reports_dir: Path) -> dict[str, Path]:
    if not lead_reports_dir.exists():
        return {}
    reports = {}
    for report_json in sorted(lead_reports_dir.rglob("report.json")):
        mol_id = report_json.parent.name
        reports[mol_id] = report_json
    return reports


def _partial_dirs(lead_reports_dir: Path) -> list[str]:
    if not lead_reports_dir.exists():
        return []
    partial = []
    for path in sorted(lead_reports_dir.iterdir()):
        if path.is_dir() and not (path / "report.json").exists():
            partial.append(path.name)
    return partial


def _write_outputs(pilot_root: Path, status: dict[str, Any]) -> tuple[Path, Path]:
    logs_dir = pilot_root / "logs"
    summaries_dir = pilot_root / "summaries"
    logs_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir.mkdir(parents=True, exist_ok=True)

    json_path = logs_dir / "shard_status.json"
    json_path.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")

    md_lines = [
        "# ChEMBL Cluster Pilot Shard Status",
        "",
        f"- Pilot root: `{pilot_root}`",
        f"- Full panel size: `{status['full_panel_size']}`",
        f"- Main merged completed parents: `{status['main_completed_count']}`",
        f"- Unique completed parents across shards: `{status['unique_shard_completed_count']}`",
        f"- Remaining incomplete parents after shard completion: `{status['remaining_incomplete_count']}`",
        f"- Remaining unmerged parents in main root: `{status['remaining_unmerged_count']}`",
        "",
        "## Main pilot root",
        "",
    ]
    main_ids = status["main_completed_parent_ids"]
    md_lines.append(f"- Completed parent ids: `{', '.join(main_ids) if main_ids else 'none'}`")
    if status["duplicate_audit_partial_dir"]:
        md_lines.append(
            f"- Stale duplicate audit subtree present: `{status['duplicate_audit_partial_dir']}`"
        )
    md_lines.extend(["", "## Shards", ""])

    for shard_name in sorted(status["shards"]):
        shard = status["shards"][shard_name]
        md_lines.extend(
            [
                f"### {shard_name}",
                "",
                f"- Panel size: `{shard['panel_count']}`",
                f"- Completed: `{shard['completed_count']}`",
                f"- Missing: `{shard['missing_count']}`",
                f"- Completed parent ids: `{', '.join(shard['completed_parent_ids']) if shard['completed_parent_ids'] else 'none'}`",
                f"- Missing parent ids: `{', '.join(shard['missing_parent_ids']) if shard['missing_parent_ids'] else 'none'}`",
                f"- Partial parent dirs without report.json: `{', '.join(shard['partial_parent_dirs']) if shard['partial_parent_dirs'] else 'none'}`",
                "",
            ]
        )

    md_path = summaries_dir / "shard_status.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return json_path, md_path


def build_status(pilot_root: Path) -> dict[str, Any]:
    panel_path = pilot_root / "inputs_snapshot" / "chembl_cluster_pilot_parent_panel.csv"
    full_panel_ids = _panel_ids(panel_path)

    main_reports = _completed_reports(pilot_root / "generation" / "run" / "lead_reports")
    shards_root = pilot_root / "shards"
    shard_status: dict[str, Any] = {}
    shard_completed_union: set[str] = set()
    shard_completed_dupes: dict[str, list[str]] = {}

    for shard_dir in sorted([p for p in shards_root.iterdir() if p.is_dir()]):
        shard_name = shard_dir.name
        shard_panel_name = f"chembl_cluster_pilot_{shard_name}.csv"
        shard_panel_path = pilot_root / "inputs_snapshot" / "shards" / shard_panel_name
        shard_ids = _panel_ids(shard_panel_path)
        completed = _completed_reports(shard_dir / "generation" / "run" / "lead_reports")
        partial = _partial_dirs(shard_dir / "generation" / "run" / "lead_reports")
        missing = [mol_id for mol_id in shard_ids if mol_id not in completed]
        for mol_id in completed:
            shard_completed_dupes.setdefault(mol_id, []).append(shard_name)
            shard_completed_union.add(mol_id)

        shard_status[shard_name] = {
            "panel_path": str(shard_panel_path.resolve()),
            "panel_count": len(shard_ids),
            "completed_count": len(completed),
            "completed_parent_ids": sorted(completed),
            "missing_count": len(missing),
            "missing_parent_ids": missing,
            "partial_parent_dirs": partial,
            "output_root": str(shard_dir.resolve()),
        }

    duplicate_completions = {
        mol_id: shard_names
        for mol_id, shard_names in sorted(shard_completed_dupes.items())
        if len(shard_names) > 1
    }
    main_ids = sorted(main_reports)
    remaining_after_shards = [mol_id for mol_id in full_panel_ids if mol_id not in shard_completed_union]
    remaining_unmerged = [mol_id for mol_id in full_panel_ids if mol_id not in main_reports]

    status = {
        "pilot_root": str(pilot_root.resolve()),
        "panel_path": str(panel_path.resolve()),
        "full_panel_size": len(full_panel_ids),
        "main_completed_count": len(main_reports),
        "main_completed_parent_ids": main_ids,
        "unique_shard_completed_count": len(shard_completed_union),
        "unique_shard_completed_parent_ids": sorted(shard_completed_union),
        # This is the operationally relevant count while shard jobs are active.
        "remaining_incomplete_count": len(remaining_after_shards),
        "remaining_incomplete_parent_ids": remaining_after_shards,
        # This tracks merge lag between shard outputs and the main pilot root.
        "remaining_unmerged_count": len(remaining_unmerged),
        "remaining_unmerged_parent_ids": remaining_unmerged,
        "duplicate_completed_parents_across_shards": duplicate_completions,
        "duplicate_audit_partial_dir": (
            str((pilot_root / "audit_partial_b0507").resolve())
            if (pilot_root / "audit_partial_b0507").exists()
            else None
        ),
        "shards": shard_status,
    }
    return status


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the current ChEMBL Cluster pilot shard state and write a status snapshot."
    )
    parser.add_argument(
        "--pilot-root",
        type=Path,
        default=Path("reports/lead_opt_literature_audit_chembl/cluster_pilot"),
        help="Pilot root to inspect.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    pilot_root = _resolve(args.pilot_root)
    status = build_status(pilot_root)
    json_path, md_path = _write_outputs(pilot_root, status)

    print("ChEMBL Cluster Pilot Status")
    print(f"  - pilot_root: {pilot_root}")
    print(f"  - full_panel_size: {status['full_panel_size']}")
    print(f"  - main_completed_count: {status['main_completed_count']}")
    print(f"  - unique_shard_completed_count: {status['unique_shard_completed_count']}")
    print(f"  - remaining_incomplete_count: {status['remaining_incomplete_count']}")
    print(f"  - remaining_unmerged_count: {status['remaining_unmerged_count']}")
    print(f"  - main_completed_parent_ids: {status['main_completed_parent_ids']}")
    for shard_name in sorted(status["shards"]):
        shard = status["shards"][shard_name]
        print(
            f"  - shard {shard_name}: panel={shard['panel_count']} "
            f"completed={shard['completed_count']} missing={shard['missing_count']} "
            f"partial_dirs={len(shard['partial_parent_dirs'])}"
        )
    if status["duplicate_completed_parents_across_shards"]:
        print(f"  - duplicate_completed_parents_across_shards: {status['duplicate_completed_parents_across_shards']}")
    if status["duplicate_audit_partial_dir"]:
        print(f"  - stale_duplicate_audit_dir: {status['duplicate_audit_partial_dir']}")
    print(f"  - wrote_json: {json_path}")
    print(f"  - wrote_markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
