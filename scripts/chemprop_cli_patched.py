#!/usr/bin/env python3
"""ChemProp CLI wrapper for the ChemProp 2.2.2 PRC checkpointing bug.

ChemProp 2.2.2 leaves ``BinaryAUPRC.higher_is_better`` unset, so it inherits
``False`` from ``ChempropMetric``. When ``tracking_metric=prc``, Lightning
therefore configures ModelCheckpoint and EarlyStopping with ``mode="min"`` and
selects the worst PRC epoch instead of the best one.

This wrapper is only used for legacy runs that still request
``tracking_metric=prc``. Normal Stage 2 configs should now use
``tracking_metric=auroc``; the local runner maps that to ChemProp's CLI alias
``roc``, which is correctly marked ``higher_is_better=True``.

Delete this file once either:
1. ChemProp fixes the upstream ``BinaryAUPRC.higher_is_better`` bug.
2. All local configs and manual overrides have been migrated to ``auroc``.

Upstream reference: no ChemProp issue number is pinned in this repository for
this bug as of this patch; verify the ChemProp tracker before removing the
wrapper.
"""

from __future__ import annotations

from chemprop.cli.main import main as chemprop_main
from chemprop.nn.metrics import BinaryAUPRC, MetricRegistry


def _patch_prc_tracking() -> None:
    # ChemProp 2.2.2 leaves PRC with lower_is_better semantics, which inverts
    # ModelCheckpoint and EarlyStopping when tracking_metric=prc.
    BinaryAUPRC.higher_is_better = True
    MetricRegistry["prc"].higher_is_better = True


if __name__ == "__main__":
    _patch_prc_tracking()
    chemprop_main()
