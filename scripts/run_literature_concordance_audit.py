#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hergbench.reporting.literature_concordance import build_audit_outputs


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a literature-concordance audit on existing lead-optimization "
            "outputs using a simple heuristic anti-hERG rubric."
        )
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("reports/runs"),
        help=(
            "Run directory, lead_reports directory, or parent directory containing run "
            "directories with lead_reports. Default: reports/runs"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports/lead_opt_literature_audit_chembl"),
        help=(
            "Output root for the literature-concordance audit. "
            "Default: reports/lead_opt_literature_audit_chembl"
        ),
    )
    parser.add_argument(
        "--dataset",
        choices=["tdc", "chembl"],
        default=None,
        help="Optional dataset label override.",
    )
    parser.add_argument(
        "--split-type",
        choices=["random", "scaffold", "cluster"],
        default=None,
        help="Optional upstream split regime filter.",
    )
    parser.add_argument(
        "--include-tier4",
        action="store_true",
        help="Include Tier 4 diagnostic fallback candidates in the analysis cohort.",
    )
    parser.set_defaults(best_per_parent_only=True)
    parser.add_argument(
        "--best-per-parent-only",
        dest="best_per_parent_only",
        action="store_true",
        help=(
            "Analyze only the single best retained candidate per parent. "
            "This is the default cohort mode."
        ),
    )
    parser.add_argument(
        "--all-candidates",
        dest="best_per_parent_only",
        action="store_false",
        help="Analyze all retained candidates instead of one best candidate per parent.",
    )
    parser.add_argument(
        "--scaffold-preserved-only",
        action="store_true",
        help="Restrict the analysis cohort to scaffold-preserved candidates only.",
    )
    parser.add_argument(
        "--min-similarity-to-parent",
        type=float,
        default=None,
        help="Minimum candidate-to-parent similarity required in the analysis cohort.",
    )
    parser.add_argument(
        "--join-parent-novelty-from",
        type=Path,
        default=None,
        help=(
            "Optional CSV providing parent max_sim_to_train and/or sim_bin for novelty "
            "stratification."
        ),
    )
    parser.add_argument(
        "--parent-panel-file",
        type=Path,
        default=None,
        help=(
            "Optional CSV with mol_id and/or smiles used to restrict the audit to a "
            "specific parent subset."
        ),
    )
    parser.add_argument(
        "--max-parents",
        type=int,
        default=None,
        help="Optional deterministic cap on the number of parent reports loaded.",
    )
    parser.set_defaults(include_relaxed=True)
    parser.add_argument(
        "--include-relaxed",
        dest="include_relaxed",
        action="store_true",
        help="Include relaxed candidates in the analysis cohort. This is the default.",
    )
    parser.add_argument(
        "--exclude-relaxed",
        dest="include_relaxed",
        action="store_false",
        help="Exclude relaxed candidates from the analysis cohort.",
    )
    parser.add_argument(
        "--include-dataset-analogues",
        action="store_true",
        help="Include dataset-analogue fallback records in addition to generated candidates.",
    )
    parser.add_argument(
        "--top-n-per-parent",
        type=int,
        default=0,
        help=(
            "Keep at most the first N retained candidates per parent before any "
            "best-per-parent reduction. Use 0 for no pre-limit. Default: 0"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of worker processes used for descriptor scoring in the audit step. "
            "Default: 1"
        ),
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=64,
        help="Chunk size passed to worker-process descriptor scoring. Default: 64",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Resume a partially completed audit by reusing an existing candidate table "
            "in the output root when run parameters match."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed audit logging while the workflow runs.",
    )
    return parser


def _format_list(paths: list[str]) -> str:
    if not paths:
        return "  - none"
    return "\n".join(f"  - {path}" for path in paths)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    artifacts, summary = build_audit_outputs(
        input_root=(REPO_ROOT / args.input_root).resolve()
        if not args.input_root.is_absolute()
        else args.input_root.resolve(),
        output_root=(REPO_ROOT / args.output_root).resolve()
        if not args.output_root.is_absolute()
        else args.output_root.resolve(),
        dataset=args.dataset,
        split_type=args.split_type,
        include_tier4=args.include_tier4,
        best_per_parent_only=args.best_per_parent_only,
        scaffold_preserved_only=args.scaffold_preserved_only,
        include_relaxed=args.include_relaxed,
        include_dataset_analogues=args.include_dataset_analogues,
        min_similarity_to_parent=args.min_similarity_to_parent,
        top_n_per_parent=args.top_n_per_parent,
        parent_panel_file=(
            (REPO_ROOT / args.parent_panel_file).resolve()
            if args.parent_panel_file is not None and not args.parent_panel_file.is_absolute()
            else args.parent_panel_file.resolve()
            if args.parent_panel_file is not None
            else None
        ),
        max_parents=args.max_parents,
        workers=args.workers,
        chunk_size=args.chunk_size,
        resume=args.resume,
        join_parent_novelty_from=(
            (REPO_ROOT / args.join_parent_novelty_from).resolve()
            if args.join_parent_novelty_from is not None
            and not args.join_parent_novelty_from.is_absolute()
            else args.join_parent_novelty_from.resolve()
            if args.join_parent_novelty_from is not None
            else None
        ),
        verbose=args.verbose,
    )

    input_manifest = json.loads(Path(artifacts.input_manifest).read_text(encoding="utf-8"))
    files_read = [
        input_manifest["lead_reports_dir"],
        *input_manifest.get("prediction_files", []),
    ]
    if input_manifest.get("metadata_path"):
        files_read.insert(1, input_manifest["metadata_path"])
    if input_manifest.get("join_parent_novelty_from"):
        files_read.append(input_manifest["join_parent_novelty_from"])

    files_written = [
        str(artifacts.candidate_table),
        str(artifacts.best_table),
        str(artifacts.summary_by_similarity),
        str(artifacts.summary_by_tier),
        *( [str(artifacts.summary_by_split)] if artifacts.summary_by_split else [] ),
        str(artifacts.summary_txt),
        str(artifacts.concordance_by_similarity_fig),
        str(artifacts.rule_hit_rates_fig),
        str(artifacts.scaffold_preservation_fig),
        str(artifacts.delta_prob_vs_concordance_fig),
        str(artifacts.input_manifest),
        str(artifacts.report_manifest),
        str(artifacts.rule_snapshot),
        str(artifacts.run_parameters),
        str(artifacts.filter_counts),
        str(artifacts.log_path),
    ]

    assumptions = [
        "Tier 1-3 are treated as the default reportable cohort unless --include-tier4 is used.",
        "The serialized lead-opt field `similarity_to_train` in counterfactual records is interpreted as candidate-to-parent similarity, not train-set similarity.",
        "Parent novelty is taken from upstream prediction files when available, or from --join-parent-novelty-from if supplied.",
        "The concordance rubric is heuristic and literature-directional only; it is not a causal or experimental validation layer.",
        "Descriptor scoring can use multiple worker processes, but the scientific rule set and filtering logic are unchanged.",
    ]

    next_step = (
        "Review the best-per-parent table and the novelty-stratified summary to identify "
        "which rule directions fail most often in the most novel parent bin."
    )

    print("Built")
    print(f"  - dataset: {summary['dataset']}")
    print(f"  - reports loaded: {summary['reports_loaded']}")
    print(f"  - raw candidates parsed: {summary['raw_candidates']}")
    print(f"  - retained candidates: {summary['filtered_candidates']}")
    print(f"  - best-per-parent rows: {summary['best_per_parent']}")
    print(f"  - summary cohort parents: {summary['summary_parents']}")
    print(f"  - workers: {args.workers}")
    print(f"  - resume: {args.resume}")
    print(f"  - output root: {Path(artifacts.candidate_table).parents[1]}")
    print("")
    print("Assumptions")
    print(_format_list(assumptions))
    print("")
    print("Existing Files Read")
    print(_format_list(files_read))
    print("")
    print("New Files Written")
    print(_format_list(files_written))
    print("")
    print("Next Recommended Analysis")
    print(f"  - {next_step}")
    if summary.get("warnings"):
        print("")
        print("Warnings")
        print(_format_list(summary["warnings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
