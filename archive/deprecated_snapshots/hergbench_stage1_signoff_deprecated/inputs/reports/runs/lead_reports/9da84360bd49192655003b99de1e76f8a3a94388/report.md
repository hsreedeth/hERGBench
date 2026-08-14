# Lead Optimization Report — 9da84360bd49192655003b99de1e76f8a3a94388
## Summary
- **Calibrated p(toxic):** 0.596
- **Threshold:** 0.510 → **Predicted class:** 1
- **Max similarity to train:** 0.312 (**bin:** 0.3-0.5)
- **OOD classification:** Out-of-domain
- **Result classification:** Generated suggestions available (Tier: Tier 1 — Flip)
- Similarity is low; treat any suggestions cautiously and consult fallback analogues.
## Base molecule
- **SMILES:** `CC(C)c1nc(CN(C)C(=O)NC(C(=O)N[C@@H](Cc2ccccc2)C[C@H](O)[C@H](Cc2ccccc2)NC(=O)OCc2cncs2)C(C)C)cs1`
- **True label:** 1

![](base.png)

## Counterfactual search summary
- ExMol requested: 1800 | drawn: 1581
- Generated tier (Tier 1–4): Tier 1 — Flip
- Relaxation used: True (applied: relax_sa_5.5)
- Generated survivors (Tier 1–4): 5
- Dataset analogue fallback count (not included in survivors): 2
- Relaxation note: raise SA max to 5.5

### Filter attrition by tier (baseline + final relaxation)
<table>
<tr><th>Tier</th><th>Relaxation</th><th>Sampled</th><th>Kept</th><th>Invalid</th><th>Duplicate</th><th>Similarity</th><th>Prob</th><th>Δp</th><th>SA</th><th>ΔLogP</th><th>QED</th><th>Alerts</th></tr>
<tr><td>Tier 1 — Flip</td><td>none</td><td>1581</td><td>0</td><td>0</td><td>3</td><td>547</td><td>1008</td><td>0</td><td>22</td><td>1</td><td>0</td><td>0</td></tr>
<tr><td>Tier 1 — Flip</td><td>relax_sa_5.5</td><td>1581</td><td>6</td><td>0</td><td>3</td><td>547</td><td>1008</td><td>0</td><td>6</td><td>2</td><td>0</td><td>9</td></tr>
</table>

<details><summary>All filter attempts (diagnostic)</summary>
```json
[
  {
    "tier": "flip",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "none",
    "relaxation_desc": "baseline constraints",
    "counts": {
      "sampled": 1581,
      "invalid": 0,
      "duplicate": 3,
      "similarity_filtered": 547,
      "prob_filtered": 1008,
      "delta_filtered": 0,
      "sa_filtered": 22,
      "logp_filtered": 1,
      "qed_filtered": 0,
      "alert_filtered": 0,
      "kept": 0,
      "min_tanimoto_used": 0.5,
      "min_tanimoto_source": "min_tanimoto_flip",
      "prob_max_used": 0.509999,
      "delta_min_used": null,
      "sa_max_used": 4.5,
      "logp_delta_max_used": 1.5,
      "qed_min_used": 0.0,
      "pains_used": true
    }
  },
  {
    "tier": "flip",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_flip_0.4",
    "relaxation_desc": "lower flip min_tanimoto to 0.4",
    "counts": {
      "sampled": 1581,
      "invalid": 0,
      "duplicate": 3,
      "similarity_filtered": 294,
      "prob_filtered": 1238,
      "delta_filtered": 0,
      "sa_filtered": 40,
      "logp_filtered": 6,
      "qed_filtered": 0,
      "alert_filtered": 0,
      "kept": 0,
      "min_tanimoto_used": 0.4,
      "min_tanimoto_source": "min_tanimoto_flip",
      "prob_max_used": 0.509999,
      "delta_min_used": null,
      "sa_max_used": 4.5,
      "logp_delta_max_used": 1.5,
      "qed_min_used": 0.0,
      "pains_used": true
    }
  },
  {
    "tier": "flip",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_flip_0.3",
    "relaxation_desc": "lower flip min_tanimoto to 0.3",
    "counts": {
      "sampled": 1581,
      "invalid": 0,
      "duplicate": 3,
      "similarity_filtered": 138,
      "prob_filtered": 1358,
      "delta_filtered": 0,
      "sa_filtered": 67,
      "logp_filtered": 15,
      "qed_filtered": 0,
      "alert_filtered": 0,
      "kept": 0,
      "min_tanimoto_used": 0.3,
      "min_tanimoto_source": "min_tanimoto_flip",
      "prob_max_used": 0.509999,
      "delta_min_used": null,
      "sa_max_used": 4.5,
      "logp_delta_max_used": 1.5,
      "qed_min_used": 0.0,
      "pains_used": true
    }
  },
  {
    "tier": "flip",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_improve_0.6",
    "relaxation_desc": "lower improve min_tanimoto to 0.6",
    "counts": {
      "sampled": 1581,
      "invalid": 0,
      "duplicate": 3,
      "similarity_filtered": 547,
      "prob_filtered": 1008,
      "delta_filtered": 0,
      "sa_filtered": 22,
      "logp_filtered": 1,
      "qed_filtered": 0,
      "alert_filtered": 0,
      "kept": 0,
      "min_tanimoto_used": 0.5,
      "min_tanimoto_source": "min_tanimoto_flip",
      "prob_max_used": 0.509999,
      "delta_min_used": null,
      "sa_max_used": 4.5,
      "logp_delta_max_used": 1.5,
      "qed_min_used": 0.0,
      "pains_used": true
    }
  },
  {
    "tier": "flip",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_improve_0.5",
    "relaxation_desc": "lower improve min_tanimoto to 0.5",
    "counts": {
      "sampled": 1581,
      "invalid": 0,
      "duplicate": 3,
      "similarity_filtered": 547,
      "prob_filtered": 1008,
      "delta_filtered": 0,
      "sa_filtered": 22,
      "logp_filtered": 1,
      "qed_filtered": 0,
      "alert_filtered": 0,
      "kept": 0,
      "min_tanimoto_used": 0.5,
      "min_tanimoto_source": "min_tanimoto_flip",
      "prob_max_used": 0.509999,
      "delta_min_used": null,
      "sa_max_used": 4.5,
      "logp_delta_max_used": 1.5,
      "qed_min_used": 0.0,
      "pains_used": true
    }
  },
  {
    "tier": "flip",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_sa_5.5",
    "relaxation_desc": "raise SA max to 5.5",
    "counts": {
      "sampled": 1581,
      "invalid": 0,
      "duplicate": 3,
      "similarity_filtered": 547,
      "prob_filtered": 1008,
      "delta_filtered": 0,
      "sa_filtered": 6,
      "logp_filtered": 2,
      "qed_filtered": 0,
      "alert_filtered": 9,
      "kept": 6,
      "min_tanimoto_used": 0.5,
      "min_tanimoto_source": "min_tanimoto_flip",
      "prob_max_used": 0.509999,
      "delta_min_used": null,
      "sa_max_used": 5.5,
      "logp_delta_max_used": 1.5,
      "qed_min_used": 0.0,
      "pains_used": true
    }
  }
]
```
</details>

## Counterfactual suggestions (filtered)
_Rows below are generated from Tier 1 — Flip (relaxation: relax_sa_5.5)._ 
<table>
<tr><th>Rank</th><th>Structure</th><th>Tier</th><th>Relaxation</th><th>Similarity</th><th>p(toxic)</th><th>Δp</th><th>LogP</th><th>QED</th><th>SA</th></tr>
<tr><td>1</td><td><img src="cf_01.png" width="260"></td><td>Tier 1 — Flip</td><td>relax_sa_5.5</td><td>0.190</td><td>0.459</td><td>0.137</td><td>6.16</td><td>0.15</td><td>5.37</td></tr>
<tr><td>2</td><td><img src="cf_02.png" width="260"></td><td>Tier 1 — Flip</td><td>relax_sa_5.5</td><td>0.157</td><td>0.471</td><td>0.126</td><td>6.04</td><td>0.18</td><td>5.15</td></tr>
<tr><td>3</td><td><img src="cf_03.png" width="260"></td><td>Tier 1 — Flip</td><td>relax_sa_5.5</td><td>0.221</td><td>0.499</td><td>0.097</td><td>6.11</td><td>0.18</td><td>5.23</td></tr>
<tr><td>4</td><td><img src="cf_04.png" width="260"></td><td>Tier 1 — Flip</td><td>relax_sa_5.5</td><td>0.211</td><td>0.499</td><td>0.097</td><td>5.31</td><td>0.19</td><td>5.49</td></tr>
<tr><td>5</td><td><img src="cf_05.png" width="260"></td><td>Tier 1 — Flip</td><td>relax_sa_5.5</td><td>0.327</td><td>0.505</td><td>0.092</td><td>5.47</td><td>0.13</td><td>4.58</td></tr>
</table>

## Dataset-derived analogues (fallback)
_Nearest analogues from the dataset (context only, not generated edits)._ 
<table>
<tr><th>Rank</th><th>Structure</th><th>Similarity</th><th>p(toxic)</th><th>Δp</th><th>LogP</th><th>QED</th><th>SA</th><th>Alerts</th><th>Actionable?</th></tr>
<tr><td>1</td><td><img src="ds_01.png" width="260"></td><td>0.312</td><td>0.635</td><td>-0.039</td><td>4.33</td><td>0.20</td><td>3.90</td><td>OK</td><td>NO</td></tr>
<tr><td>2</td><td><img src="ds_02.png" width="260"></td><td>0.312</td><td>0.635</td><td>-0.039</td><td>4.33</td><td>0.20</td><td>3.90</td><td>OK</td><td>NO</td></tr>
</table>
Fallback analogues are context-only; none meet feasibility constraints.

## Raw records (for audit)
### Counterfactuals JSON
```json
[
  {
    "raw_smiles": "CC1=C(C[C@@H](C[C@H](O)[C@H](CC=C2C=CC=C=N2)NC(=O)OCc2cncs2)NC(=O)C(NC(=O)N(C)Cc2csc(C(C)C)n2)C(C)C)C=CC1",
    "smiles": "CC1=C(C[C@@H](C[C@H](O)[C@H](CC=C2C=CC=C=N2)NC(=O)OCc2cncs2)NC(=O)C(NC(=O)N(C)Cc2csc(C(C)C)n2)C(C)C)C=CC1",
    "similarity": 0.1897810218978102,
    "p": 0.45885201181979773,
    "delta_p": 0.13749994205381844,
    "logp": 6.156000000000006,
    "qed": 0.15166654820572706,
    "sascore": 5.368212646849942,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_sa_5.5",
    "relaxation_desc": "raise SA max to 5.5",
    "p_raw": 0.45885201181979773,
    "delta_p_raw": 0.13749994205381844,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CC(C)c1nc(CN(C)C(=O)NC(C(=O)N[C@H](C[CH][C@H](CC2C=CC=CCO2)NC(=O)OCc2cncs2)CC=CF)C(C)C)cs1",
    "smiles": "CC(C)c1nc(CN(C)C(=O)NC(C(=O)N[C@H](C[CH][C@H](CC2C=CC=CCO2)NC(=O)OCc2cncs2)CC=CF)C(C)C)cs1",
    "similarity": 0.15748031496062992,
    "p": 0.4705358483640696,
    "delta_p": 0.12581610550954658,
    "logp": 6.037790000000007,
    "qed": 0.18449286446449875,
    "sascore": 5.146363334343856,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_sa_5.5",
    "relaxation_desc": "raise SA max to 5.5",
    "p_raw": 0.4705358483640696,
    "delta_p_raw": 0.12581610550954658,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CC(C)c1nc(CN(C)C(=O)NC2C(=O)N[C@H](C[C@H](O)[C@H](Cc3ccccc3)NC(=O)OCc3cncs3)CC=CC=CC=CC2(C)C)cs1",
    "smiles": "CC(C)c1nc(CN(C)C(=O)NC2C(=O)N[C@H](C[C@H](O)[C@H](Cc3ccccc3)NC(=O)OCc3cncs3)CC=CC=CC=CC2(C)C)cs1",
    "similarity": 0.22137404580152673,
    "p": 0.49936484759973077,
    "delta_p": 0.0969871062738854,
    "logp": 6.1050000000000075,
    "qed": 0.1768663615049475,
    "sascore": 5.234936881003394,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_sa_5.5",
    "relaxation_desc": "raise SA max to 5.5",
    "p_raw": 0.49936484759973077,
    "delta_p_raw": 0.0969871062738854,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CC(C)c1nc(CN(C)C(=O)NC2C(=O)N[C@H](C[C@H](O)[C@H](Cc3ccccc3)NC(=O)OCc3cncs3)CC=CC=C=CC2C)cs1",
    "smiles": "CC(C)c1nc(CN(C)C(=O)NC2C(=O)N[C@H](C[C@H](O)[C@H](Cc3ccccc3)NC(=O)OCc3cncs3)CC=CC=C=CC2C)cs1",
    "similarity": 0.21052631578947367,
    "p": 0.49936484759973077,
    "delta_p": 0.0969871062738854,
    "logp": 5.313800000000007,
    "qed": 0.18828341491967526,
    "sascore": 5.485405285292968,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_sa_5.5",
    "relaxation_desc": "raise SA max to 5.5",
    "p_raw": 0.49936484759973077,
    "delta_p_raw": 0.0969871062738854,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CC(C)C(NC(=O)N(C)CC1=CSCCC(C)(C)N1)C(=O)N[C@@H](Cc1ccccc1)C[C@H](O)[C@H](Cc1ccccc1)NC(=O)OCc1cncs1",
    "smiles": "CC(C)C(NC(=O)N(C)CC1=CSCCC(C)(C)N1)C(=O)N[C@@H](Cc1ccccc1)C[C@H](O)[C@H](Cc1ccccc1)NC(=O)OCc1cncs1",
    "similarity": 0.3274336283185841,
    "p": 0.5045758333908558,
    "delta_p": 0.0917761204827604,
    "logp": 5.471600000000003,
    "qed": 0.13031612609520576,
    "sascore": 4.576360797737516,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "relax_sa_5.5",
    "relaxation_desc": "raise SA max to 5.5",
    "p_raw": 0.5045758333908558,
    "delta_p_raw": 0.0917761204827604,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  }
]
```
### Dataset analogues JSON
```json
[
  {
    "raw_smiles": "Cc1cccc(C)c1OCC(=O)NC(Cc1ccccc1)C(O)CC(Cc1ccccc1)NC(=O)C(C(C)C)N1CCCNC1=O",
    "smiles": "Cc1cccc(C)c1OCC(=O)NC(Cc1ccccc1)C(O)CC(Cc1ccccc1)NC(=O)C(C(C)C)N1CCCNC1=O",
    "similarity": 0.3119266055045872,
    "p": 0.6351279811453759,
    "delta_p": -0.03877602727175977,
    "logp": 4.328140000000003,
    "qed": 0.199874123748593,
    "sascore": 3.8968328243566237,
    "sa_status": "ok",
    "actionable": false,
    "alert": false,
    "tier": "dataset_analogue",
    "tier_label": "Dataset analogue",
    "relaxation": "none",
    "relaxation_desc": "dataset fallback",
    "sa_max_used": 4.5,
    "pains_used": true
  },
  {
    "raw_smiles": "Cc1cccc(C)c1OCC(=O)N[C@H](Cc1ccccc1)[C@H](O)C[C@@H](Cc1ccccc1)NC(=O)C(C(C)C)N1CCCNC1=O",
    "smiles": "Cc1cccc(C)c1OCC(=O)N[C@H](Cc1ccccc1)[C@H](O)C[C@@H](Cc1ccccc1)NC(=O)C(C(C)C)N1CCCNC1=O",
    "similarity": 0.3119266055045872,
    "p": 0.6351279811453759,
    "delta_p": -0.03877602727175977,
    "logp": 4.328140000000003,
    "qed": 0.199874123748593,
    "sascore": 3.8968328243566237,
    "sa_status": "ok",
    "actionable": false,
    "alert": false,
    "tier": "dataset_analogue",
    "tier_label": "Dataset analogue",
    "relaxation": "none",
    "relaxation_desc": "dataset fallback",
    "sa_max_used": 4.5,
    "pains_used": true
  }
]
```
