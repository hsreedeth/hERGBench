# Stage 1 Prescriptive QC (Representative Lead Report)
**Base SMILES (std):** `O=C1NCCN1CC[NH+]1CC=C(c2cn(-c3ccc(F)cc3)c3ccc(Cl)cc23)CC1`  
**Operating threshold:** 0.51  
**Base p(toxic):** 0.6612598146460736  
**Max similarity to train (AD proxy):** 0.7
## Similarity-to-base confirmation
Similarity-to-base was computed using Morgan fingerprints (radius=2, 2048 bits) and Tanimoto similarity. This complements the report’s similarity-to-train and quantifies local edit plausibility.
## Threshold robustness
Each counterfactual was evaluated under a threshold sweep (0.40–0.70). We report the fraction of thresholds under which the molecule remains classified as non-toxic, and the margin at the operating threshold.
## Medicinal feasibility proxies
We evaluated scaffold continuity using Murcko scaffold identity and MCS overlap ratio, and performed an independent structural alert screen (PAINS-A, Brenk, NIH). Basic property deltas (MW/TPSA/HBD/HBA/RB/rings) were computed relative to the base.
## Top candidate summary (for reporting)
- CF idx=1: p=0.406, Δp=0.255, sim_to_base=0.337, scaffold_same=False, mcs_ratio=0.77, - CF idx=2: p=0.412, Δp=0.250, sim_to_base=0.356, scaffold_same=False, mcs_ratio=0.77, - CF idx=3: p=0.422, Δp=0.239, sim_to_base=0.384, scaffold_same=False, mcs_ratio=0.77, 