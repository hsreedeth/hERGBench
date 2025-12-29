from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def fetch_tdc_herg(cfg: dict[str, Any], logger) -> Path:
    """
    Fetch the hERG dataset via TDC and save as a CSV in data/raw/.

    Notes:
    - TDC API details can shift; this function is isolated so your pipeline core is stable.
    - Stage 1 will validate the dataset name and schema (SMILES + label columns).
    """
    raw_dir = Path(cfg["paths"]["data_raw"])
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Attempt common TDC pattern
    try:
        from tdc.single_pred import ADME  # type: ignore

        data = ADME(name="hERG")  # naming may differ depending on TDC version
        df = data.get_data()
    except Exception:
        # Fallback: do nothing but fail loudly here (caller treats as optional)
        raise RuntimeError("Unable to fetch TDC hERG via current TDC API. Verify dataset name/version.")

    if not isinstance(df, pd.DataFrame):
        raise TypeError("TDC returned non-DataFrame data.")

    out_path = raw_dir / "tdc_herg.csv"
    df.to_csv(out_path, index=False)
    logger.info("Saved %d rows to %s", len(df), out_path)
    return out_path


# this is intentionally boxed off. if he name changes on install, correctuion is to be made here and not the entire pipeline. !!
