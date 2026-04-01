"""
ChEMBL hERG bioactivity curation pipeline.

Fetches CHEMBL240 (KCNH2/hERG) binding data, applies a multi-step curation
funnel, deduplicates against the TDC dataset, standardizes SMILES, and
generates train/val/test splits that match the existing pipeline format.

Output format mirrors data/processed/herg_clean.csv exactly:
    mol_id (str) — SHA-1 hash of canonical SMILES
    smiles (str) — canonical standardized SMILES
    y      (int) — 1 = hERG blocker, 0 = non-blocker
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── Constants ────────────────────────────────────────────────────────────────

_CHEMBL_TARGET = "CHEMBL240"
_REST_BASE = "https://www.ebi.ac.uk/chembl/api/data"
_REST_FIELDS = (
    "molecule_chembl_id,canonical_smiles,standard_type,standard_value,"
    "standard_units,standard_relation,assay_chembl_id,pchembl_value,"
    "data_validity_comment,src_id"
)
_PAGE_SIZE = 1000
_SPLIT_TYPES = ["random", "scaffold", "cluster"]
_SEEDS = [11, 22, 33, 44, 55]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mol_id(smiles: str) -> str:
    """SHA-1 hash of canonical SMILES — matches project mol_id convention."""
    return hashlib.sha1(smiles.encode()).hexdigest()


def _inchikey(mol) -> Optional[str]:
    """Compute InChIKey for an RDKit Mol; return None on failure."""
    try:
        from rdkit.Chem import inchi as rdkit_inchi
        inchi = rdkit_inchi.MolToInchi(mol)
        if inchi is None:
            return None
        return rdkit_inchi.InchiToInchiKey(inchi)
    except Exception:
        return None


def _std_smiles(smiles: str):
    """Return (canonical_smiles, mol) using project standardization. Returns (None, None) on failure."""
    from hergbench.data.standardize import (
        StandardizeConfig, canonical_smiles, smiles_to_mol, standardize_mol,
    )
    std_cfg = StandardizeConfig(tautomer_canonicalize=True, strip_salts=True)
    mol = smiles_to_mol(smiles)
    mol = standardize_mol(mol, std_cfg)
    if mol is None:
        return None, None
    try:
        smi = canonical_smiles(mol)
        return smi, mol
    except Exception:
        return None, None


# ── Step 1: Fetch ─────────────────────────────────────────────────────────────

def _fetch_via_client() -> pd.DataFrame:
    """Fetch using chembl_webresource_client (preferred — handles pagination)."""
    from chembl_webresource_client.new_client import new_client  # type: ignore

    print("[fetch] Using chembl_webresource_client...")
    activity = new_client.activity
    results = activity.filter(
        target_chembl_id=_CHEMBL_TARGET,
        assay_type="B",
        standard_type__in=["IC50", "Ki"],
        standard_units="nM",
        standard_relation="=",
    ).only(_REST_FIELDS.split(","))

    rows = list(results)
    print(f"[fetch]   Retrieved {len(rows)} records via client.")
    return pd.DataFrame(rows)


def _make_ssl_context():
    """Return an SSL context, trying certifi certs first then system certs."""
    import ssl
    try:
        import certifi  # type: ignore
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except ImportError:
        pass
    # Fall back to default context (works when system certs are wired correctly)
    try:
        return ssl.create_default_context()
    except Exception:
        pass
    # Last resort: unverified (macOS fresh Python install without certs configured)
    print(
        "[fetch] WARNING: SSL certificate verification disabled. "
        "Run 'pip install certifi' or '/Applications/Python*/Install Certificates.command' to fix this."
    )
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch_via_rest() -> pd.DataFrame:
    """Paginated REST API fallback."""
    import urllib.request
    import urllib.parse

    print("[fetch] Using REST API fallback (paginating)...")
    ssl_ctx = _make_ssl_context()

    params = {
        "target_chembl_id": _CHEMBL_TARGET,
        "assay_type": "B",
        "standard_type__in": "IC50,Ki",
        "standard_units": "nM",
        "standard_relation": "=",
        "only": _REST_FIELDS,
        "limit": str(_PAGE_SIZE),
        "offset": "0",
        "format": "json",
    }

    all_rows: List[dict] = []
    offset = 0
    total = None

    while True:
        params["offset"] = str(offset)
        url = f"{_REST_BASE}/activity.json?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60, context=ssl_ctx) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            raise RuntimeError(
                f"ChEMBL REST API unreachable at offset {offset}: {exc}\n"
                f"  URL: {url}\n"
                "  Check your network connection or try again later."
            ) from exc

        page = data.get("activities", [])
        all_rows.extend(page)

        if total is None:
            total = data.get("page_meta", {}).get("total_count", 0)
            print(f"[fetch]   Total records reported by API: {total}")

        offset += _PAGE_SIZE
        fetched = len(all_rows)
        if fetched % 10000 == 0 or fetched >= (total or 0):
            print(f"[fetch]   Fetched {fetched} / {total}...")

        if len(page) < _PAGE_SIZE:
            break
        time.sleep(0.1)  # polite rate limiting

    print(f"[fetch]   REST fetch complete: {len(all_rows)} records.")
    return pd.DataFrame(all_rows)


def fetch_chembl_herg(output_path: Path, cache: bool = True) -> pd.DataFrame:
    """Fetch raw ChEMBL hERG bioactivity data. Cache raw CSV to disk.

    Tries chembl_webresource_client first; falls back to paginated REST API.
    """
    output_path = Path(output_path)

    if cache and output_path.exists():
        print(f"[fetch] Loading cached raw data from {output_path}")
        return pd.read_csv(output_path, low_memory=False)

    print(f"[fetch] Querying ChEMBL for {_CHEMBL_TARGET} binding IC50/Ki data...")
    try:
        df = _fetch_via_client()
    except ImportError:
        print("[fetch] chembl_webresource_client not installed; falling back to REST API.")
        df = _fetch_via_rest()
    except Exception as exc:
        print(f"[fetch] Client failed ({exc}); falling back to REST API.")
        df = _fetch_via_rest()

    if df.empty:
        raise RuntimeError("ChEMBL fetch returned zero records. Check network and target ID.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"[fetch] Raw data saved to {output_path} ({len(df)} rows).")
    return df


# ── Step 2a: Quality filtering ───────────────────────────────────────────────

def filter_quality(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """Apply quality filters. Returns (filtered_df, attrition_counts)."""
    attrition: dict = {"raw_count": len(df)}

    # Remove rows with ChEMBL-flagged data validity issues
    mask_validity = df["data_validity_comment"].notna() & (df["data_validity_comment"] != "")
    attrition["removed_validity_flag"] = int(mask_validity.sum())
    df = df[~mask_validity].copy()

    # Remove rows with null/missing/non-positive standard_value
    df["standard_value"] = pd.to_numeric(df["standard_value"], errors="coerce")
    mask_bad_val = df["standard_value"].isna() | (df["standard_value"] <= 0)
    attrition["removed_null_value"] = int(mask_bad_val.sum())
    df = df[~mask_bad_val].copy()

    # Remove rows with missing canonical_smiles
    mask_no_smi = df["canonical_smiles"].isna() | (df["canonical_smiles"].astype(str).str.strip() == "")
    attrition["removed_null_smiles"] = int(mask_no_smi.sum())
    df = df[~mask_no_smi].copy()

    # Remove rows with missing pchembl_value (indicates ChEMBL did not validate the measurement)
    df["pchembl_value"] = pd.to_numeric(df["pchembl_value"], errors="coerce")
    mask_no_pchembl = df["pchembl_value"].isna()
    attrition["removed_no_pchembl"] = int(mask_no_pchembl.sum())
    df = df[~mask_no_pchembl].copy()

    attrition["after_quality"] = len(df)
    print(
        f"[filter] Quality filter: {attrition['raw_count']} → {attrition['after_quality']} "
        f"(removed: validity={attrition['removed_validity_flag']}, "
        f"bad_value={attrition['removed_null_value']}, "
        f"no_smiles={attrition['removed_null_smiles']}, "
        f"no_pchembl={attrition['removed_no_pchembl']})"
    )
    return df.reset_index(drop=True), attrition


# ── Step 2b: Binarization ────────────────────────────────────────────────────

def binarize_activity(df: pd.DataFrame, threshold_uM: float = 10.0) -> pd.DataFrame:
    """Convert IC50/Ki nM values to binary hERG blockage label.

    y = 1 (blocker)     if value_uM <= threshold_uM
    y = 0 (non-blocker) if value_uM >  threshold_uM
    Matches TDC convention: Y=1 means hERG blocker.
    """
    df = df.copy()
    df["value_uM"] = df["standard_value"] / 1000.0
    df["y"] = (df["value_uM"] <= threshold_uM).astype(int)

    n_blocker = int((df["y"] == 1).sum())
    n_non = int((df["y"] == 0).sum())
    print(
        f"[binarize] Threshold {threshold_uM} μM: "
        f"{n_blocker} blockers ({100*n_blocker/len(df):.1f}%), "
        f"{n_non} non-blockers."
    )
    return df


# ── Step 2c: Duplicate resolution ────────────────────────────────────────────

def resolve_duplicates(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """Resolve multiple measurements per compound (by molecule_chembl_id).

    Strategy:
    - Concordant measurements → keep median value, use agreed label.
    - Ambiguous (conflicting labels) → majority vote; ties go to blocker (conservative).
    """
    attrition: dict = {"compounds_before_dedup": len(df)}

    groups = df.groupby("molecule_chembl_id", sort=False)
    n_single = 0
    n_concordant = 0
    n_ambiguous = 0
    resolved_rows: List[dict] = []

    for chembl_id, grp in groups:
        if len(grp) == 1:
            n_single += 1
            resolved_rows.append(grp.iloc[0].to_dict())
            continue

        labels = grp["y"].values
        unique_labels = set(labels)

        if len(unique_labels) == 1:
            n_concordant += 1
            row = grp.iloc[0].to_dict()
            row["standard_value"] = float(grp["standard_value"].median())
            row["value_uM"] = row["standard_value"] / 1000.0
            row["y"] = int(labels[0])
        else:
            n_ambiguous += 1
            n_blocker = int((labels == 1).sum())
            n_non = int((labels == 0).sum())
            # Majority vote; ties → blocker (conservative)
            majority = 1 if n_blocker >= n_non else 0
            row = grp.iloc[0].to_dict()
            row["standard_value"] = float(grp["standard_value"].median())
            row["value_uM"] = row["standard_value"] / 1000.0
            row["y"] = majority

        resolved_rows.append(row)

    out = pd.DataFrame(resolved_rows).reset_index(drop=True)

    attrition["compounds_single_measurement"] = n_single
    attrition["compounds_multi_concordant"] = n_concordant
    attrition["compounds_multi_ambiguous"] = n_ambiguous
    attrition["compounds_after_dedup"] = len(out)

    print(
        f"[dedup] Compound dedup: {attrition['compounds_before_dedup']} rows → "
        f"{attrition['compounds_after_dedup']} unique compounds "
        f"(single={n_single}, concordant={n_concordant}, ambiguous={n_ambiguous})"
    )
    return out, attrition


# ── Step 2d: Deduplication against TDC ───────────────────────────────────────

def deduplicate_against_tdc(
    chembl_df: pd.DataFrame,
    tdc_path: Path,
) -> Tuple[pd.DataFrame, dict]:
    """Remove compounds present in the TDC dataset to prevent cross-dataset leakage.

    Matching uses both standardized canonical SMILES and InChIKey (catches
    tautomer / stereochemistry ambiguities that SMILES alone would miss).
    """
    from rdkit import Chem

    tdc_path = Path(tdc_path)
    if not tdc_path.exists():
        print(f"[tdc_dedup] TDC dataset not found at {tdc_path}; skipping TDC deduplication.")
        return chembl_df, {"tdc_compounds": 0, "overlap_smiles": 0,
                           "overlap_inchikey_only": 0, "total_removed": 0,
                           "chembl_before": len(chembl_df), "chembl_after": len(chembl_df)}

    tdc_df = pd.read_csv(tdc_path)
    print(f"[tdc_dedup] TDC dataset: {len(tdc_df)} compounds.")

    # Build TDC lookup sets (standardized SMILES and InChIKey)
    tdc_smiles_set: set = set()
    tdc_inchikey_set: set = set()
    for smi in tdc_df["smiles"].astype(str):
        std_smi, mol = _std_smiles(smi)
        if std_smi:
            tdc_smiles_set.add(std_smi)
        if mol is not None:
            ik = _inchikey(mol)
            if ik:
                tdc_inchikey_set.add(ik)

    # Check ChEMBL compounds against TDC sets
    keep_mask = []
    overlap_smiles = 0
    overlap_inchikey_only = 0

    chembl_smiles_col = chembl_df["canonical_smiles"].astype(str)
    for smi in chembl_smiles_col:
        std_smi, mol = _std_smiles(smi)
        in_smiles = std_smi in tdc_smiles_set if std_smi else False
        in_ik = False
        if not in_smiles and mol is not None:
            ik = _inchikey(mol)
            in_ik = (ik in tdc_inchikey_set) if ik else False

        if in_smiles:
            overlap_smiles += 1
            keep_mask.append(False)
        elif in_ik:
            overlap_inchikey_only += 1
            keep_mask.append(False)
        else:
            keep_mask.append(True)

    import numpy as np
    keep = np.array(keep_mask)
    out = chembl_df[keep].reset_index(drop=True)

    attrition = {
        "chembl_before": len(chembl_df),
        "tdc_compounds": len(tdc_df),
        "overlap_smiles": overlap_smiles,
        "overlap_inchikey_only": overlap_inchikey_only,
        "total_removed": overlap_smiles + overlap_inchikey_only,
        "chembl_after": len(out),
    }
    print(
        f"[tdc_dedup] TDC overlap: {attrition['total_removed']} removed "
        f"(SMILES match={overlap_smiles}, InChIKey-only={overlap_inchikey_only}). "
        f"{len(out)} ChEMBL compounds remain."
    )
    return out, attrition


# ── Step 2e: Standardization ─────────────────────────────────────────────────

def standardize_dataset(df: pd.DataFrame) -> Tuple[pd.DataFrame, dict]:
    """Apply project SMILES standardization; deduplicate on standardized SMILES.

    Uses hergbench.data.standardize — the same pipeline as the TDC dataset.
    Conflicts from SMILES collapse are resolved by majority vote (ties → blocker).
    """
    attrition: dict = {"before": len(df)}

    std_smiles_list: List[Optional[str]] = []
    for smi in df["canonical_smiles"].astype(str):
        std_smi, _ = _std_smiles(smi)
        std_smiles_list.append(std_smi)

    df = df.copy()
    df["smiles"] = std_smiles_list

    # Drop failures
    failed_mask = df["smiles"].isna()
    attrition["failed"] = int(failed_mask.sum())
    df = df[~failed_mask].copy()

    # Deduplicate on standardized SMILES (standardization can collapse distinct SMILES)
    pre_collapse = len(df)
    groups = df.groupby("smiles", sort=False)
    resolved_rows: List[dict] = []
    for smi, grp in groups:
        if len(grp) == 1:
            resolved_rows.append(grp.iloc[0].to_dict())
        else:
            labels = grp["y"].values
            n_blocker = int((labels == 1).sum())
            n_non = int((labels == 0).sum())
            majority = 1 if n_blocker >= n_non else 0
            row = grp.iloc[0].to_dict()
            row["y"] = majority
            resolved_rows.append(row)

    df = pd.DataFrame(resolved_rows).reset_index(drop=True)
    attrition["collapsed"] = pre_collapse - len(df)
    attrition["after"] = len(df)

    # Assign project-standard mol_id
    df["mol_id"] = df["smiles"].apply(_mol_id)

    print(
        f"[standardize] {attrition['before']} → {attrition['after']} "
        f"(failed={attrition['failed']}, collapsed={attrition['collapsed']})"
    )
    return df, attrition


# ── Step 4: Generate splits ───────────────────────────────────────────────────

def _generate_splits(
    df: pd.DataFrame,
    splits_dir: Path,
    seeds: List[int],
) -> Dict[str, Dict[int, int]]:
    """Generate 15 split CSVs (5 seeds × 3 types). Returns >0.7 bin counts."""
    from hergbench.data.splits import SplitConfig, get_or_create_split, load_split_csv
    from hergbench.features.fingerprints import FingerprintConfig, mol_to_ecfp_bits, bulk_max_tanimoto
    from rdkit import Chem

    splits_dir.mkdir(parents=True, exist_ok=True)
    cfg = SplitConfig(frac_train=0.80, frac_val=0.10, frac_test=0.10)
    fp_cfg = FingerprintConfig(radius=2, n_bits=2048)

    gt07_counts: Dict[str, Dict[int, int]] = {"cluster": {}}

    for split_type in _SPLIT_TYPES:
        for seed in seeds:
            print(f"[splits] Generating {split_type}_seed{seed}...")
            get_or_create_split(
                df=df,
                out_dir=splits_dir,
                split_type=split_type,
                seed=seed,
                cfg=cfg,
            )

            # For cluster splits, measure >0.7 bin in test set
            if split_type == "cluster":
                split_csv = splits_dir / f"{split_type}_seed{seed}.csv"
                s = load_split_csv(split_csv)
                merged = df.merge(s, on="mol_id", how="inner")
                train_df = merged[merged["split"] == "train"]
                test_df = merged[merged["split"] == "test"]

                # Compute fingerprints
                def _fps(sub):
                    fps = []
                    for smi in sub["smiles"].astype(str):
                        mol = Chem.MolFromSmiles(smi)
                        if mol is not None:
                            fps.append(mol_to_ecfp_bits(mol, fp_cfg))
                    return fps

                train_fps = _fps(train_df)
                test_fps = _fps(test_df)

                if train_fps and test_fps:
                    max_sims = bulk_max_tanimoto(test_fps, train_fps)
                    n_gt07 = int((max_sims > 0.7).sum())
                else:
                    n_gt07 = 0

                gt07_counts["cluster"][seed] = n_gt07
                print(f"[splits]   >0.7 bin (test): {n_gt07} molecules")

    return gt07_counts


# ── Main orchestrator ─────────────────────────────────────────────────────────

def curate_chembl_herg(
    output_dir: Path = Path("data/chembl"),
    tdc_path: Path = Path("data/processed/herg_clean.csv"),
    threshold_uM: float = 10.0,
    random_seeds: List[int] = None,
) -> pd.DataFrame:
    """Full ChEMBL hERG curation pipeline.

    Fetches → quality-filters → binarizes → deduplicates → standardizes →
    generates splits → saves curation report.

    Returns the final clean DataFrame (columns: mol_id, smiles, y).
    """
    if random_seeds is None:
        random_seeds = _SEEDS

    output_dir = Path(output_dir)
    raw_path = output_dir / "raw" / "chembl_herg_raw.csv"
    processed_path = output_dir / "processed" / "chembl_herg_clean.csv"
    splits_dir = output_dir / "splits"
    report_path = output_dir / "curation_report.json"

    fetch_date = str(date.today())
    report: dict = {
        "source": "ChEMBL",
        "target": f"{_CHEMBL_TARGET} (KCNH2/hERG)",
        "threshold_uM": threshold_uM,
        "fetch_date": fetch_date,
    }

    # ── 1. Fetch ──────────────────────────────────────────────────────────────
    raw_df = fetch_chembl_herg(raw_path, cache=True)
    report["raw_count"] = len(raw_df)

    # Try to get ChEMBL version from API
    try:
        import urllib.request
        ssl_ctx = _make_ssl_context()
        req = urllib.request.Request(f"{_REST_BASE}/status.json")
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as r:
            status = json.loads(r.read())
            report["chembl_version"] = status.get("chembl_db_version", "unknown")
    except Exception:
        report["chembl_version"] = "unknown"

    # ── 2a. Quality filter ────────────────────────────────────────────────────
    df, qual_attrition = filter_quality(raw_df)
    report["quality_filtered"] = qual_attrition

    # ── 2b. Binarize ──────────────────────────────────────────────────────────
    df = binarize_activity(df, threshold_uM=threshold_uM)
    report["binarized"] = {
        "blockers": int((df["y"] == 1).sum()),
        "non_blockers": int((df["y"] == 0).sum()),
        "prevalence": round(float((df["y"] == 1).mean()), 4),
    }

    # ── 2c. Resolve duplicates (by molecule_chembl_id) ────────────────────────
    df, dup_attrition = resolve_duplicates(df)
    report["duplicate_resolution"] = dup_attrition

    # ── 2d. Deduplicate against TDC ───────────────────────────────────────────
    df, tdc_attrition = deduplicate_against_tdc(df, tdc_path)
    report["tdc_overlap"] = {
        "tdc_compounds": tdc_attrition["tdc_compounds"],
        "overlap_removed": tdc_attrition["total_removed"],
        "overlap_rate": round(
            tdc_attrition["total_removed"] / tdc_attrition["tdc_compounds"]
            if tdc_attrition["tdc_compounds"] > 0 else 0.0, 4
        ),
    }

    # ── 2e. Standardize ───────────────────────────────────────────────────────
    df, std_attrition = standardize_dataset(df)
    report["standardization"] = std_attrition

    # ── 3. Final dataset ──────────────────────────────────────────────────────
    final = df[["mol_id", "smiles", "y"]].copy()
    final["y"] = final["y"].astype(int)

    n_total = len(final)
    n_blockers = int((final["y"] == 1).sum())
    n_non = n_total - n_blockers
    report["final_dataset"] = {
        "n_compounds": n_total,
        "n_blockers": n_blockers,
        "n_non_blockers": n_non,
        "prevalence": round(n_blockers / n_total, 4) if n_total > 0 else 0.0,
    }

    processed_path.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(processed_path, index=False)
    print(f"[output] Clean dataset saved to {processed_path} ({n_total} compounds).")

    # ── 4. Splits ─────────────────────────────────────────────────────────────
    gt07_counts = _generate_splits(final, splits_dir, random_seeds)

    gt07_cluster = gt07_counts.get("cluster", {})
    report["split_validation"] = {
        "cluster_gt07_bin": {
            **{f"seed_{s}": gt07_cluster.get(s, 0) for s in random_seeds},
            "mean": round(
                sum(gt07_cluster.values()) / len(gt07_cluster)
                if gt07_cluster else 0.0, 1
            ),
        }
    }

    # ── 5. Curation report ────────────────────────────────────────────────────
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[output] Curation report saved to {report_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    q = report["quality_filtered"]
    d = report["duplicate_resolution"]
    s = report["standardization"]
    t = report["tdc_overlap"]
    fds = report["final_dataset"]
    gt07 = report["split_validation"]["cluster_gt07_bin"]

    print(f"""
ChEMBL hERG curation complete:
  Raw fetched:            {report['raw_count']:>6}
  After quality filter:   {q['after_quality']:>6}
  After binarization:     {q['after_quality']:>6}  ({report['binarized']['prevalence']*100:.1f}% blockers)
  After dedup (internal): {d['compounds_after_dedup']:>6}
  Removed (TDC overlap):  {t['overlap_removed']:>6}
  After standardization:  {s['after']:>6}
  Final dataset:          {fds['n_compounds']:>6}  compounds ({fds['prevalence']*100:.1f}% blockers)

  Cluster split >0.7 bin (test set):
""" + "\n".join(
        f"    seed {s_}: {gt07.get(f'seed_{s_}', 0)} molecules"
        for s_ in random_seeds
    ))

    return final
