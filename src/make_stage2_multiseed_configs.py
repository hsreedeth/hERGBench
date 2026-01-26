from pathlib import Path
import yaml

BASE = yaml.safe_load(Path("configs/stage2_chemprop.yaml").read_text())

SIGNOFF_SPLITS_ROOT = "hERGBench_Stage1_SignOff_v2_triple_seed11/inputs/splits"
OUTDIR = Path("configs/stage2_multiseed")
OUTDIR.mkdir(parents=True, exist_ok=True)

seeds = [11, 22, 33, 44, 55]  # choose 3–5
splits = ["random", "scaffold", "cluster"]

for split in splits:
    for s in seeds:
        cfg = dict(BASE)
        cfg["run_name"] = f"stage2_chemprop_dmnn__{split}__seed11__torch{s}"
        cfg["splits"]["membership_path"] = f"{SIGNOFF_SPLITS_ROOT}/{split}_seed11.csv"
        cfg["chemprop"]["pytorch_seed"] = s
        # Keep CPU guard in pipeline; leave accelerator/devices in config if you like.

        out = OUTDIR / f"stage2_chemprop_{split}_seed11_torch{s}.yaml"
        out.write_text(yaml.safe_dump(cfg, sort_keys=False))

print(f"Wrote configs to: {OUTDIR}")
