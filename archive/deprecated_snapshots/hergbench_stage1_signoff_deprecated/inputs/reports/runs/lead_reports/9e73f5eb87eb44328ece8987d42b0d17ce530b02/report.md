# Lead Optimization Report — 9e73f5eb87eb44328ece8987d42b0d17ce530b02
## Summary
- **Calibrated p(toxic):** 0.559
- **Threshold:** 0.510 → **Predicted class:** 1
- **Max similarity to train:** 0.375 (**bin:** 0.3-0.5)
- **OOD classification:** Out-of-domain
- **Result classification:** Generated suggestions available (Tier: Tier 1 — Flip)
- Similarity is low; treat any suggestions cautiously and consult fallback analogues.
## Base molecule
- **SMILES:** `CCS(=O)(=O)N(C)[C@H]1c2cc(C#N)ccc2OC(C)(C)[C@@H]1O`
- **True label:** 1

![](base.png)

## Counterfactual search summary
- ExMol requested: 1800 | drawn: 1436
- Generated tier (Tier 1–4): Tier 1 — Flip
- Relaxation used: False (applied: none)
- Generated survivors (Tier 1–4): 5
- Dataset analogue fallback count (not included in survivors): 1
- Relaxation note: baseline constraints

### Filter attrition by tier (baseline + final relaxation)
<table>
<tr><th>Tier</th><th>Relaxation</th><th>Sampled</th><th>Kept</th><th>Invalid</th><th>Duplicate</th><th>Similarity</th><th>Prob</th><th>Δp</th><th>SA</th><th>ΔLogP</th><th>QED</th><th>Alerts</th></tr>
<tr><td>Tier 1 — Flip</td><td>none</td><td>1436</td><td>20</td><td>0</td><td>3</td><td>1151</td><td>194</td><td>0</td><td>21</td><td>1</td><td>0</td><td>46</td></tr>
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
      "sampled": 1436,
      "invalid": 0,
      "duplicate": 3,
      "similarity_filtered": 1151,
      "prob_filtered": 194,
      "delta_filtered": 0,
      "sa_filtered": 21,
      "logp_filtered": 1,
      "qed_filtered": 0,
      "alert_filtered": 46,
      "kept": 20,
      "min_tanimoto_used": 0.5,
      "min_tanimoto_source": "min_tanimoto_flip",
      "prob_max_used": 0.509999,
      "delta_min_used": null,
      "sa_max_used": 4.5,
      "logp_delta_max_used": 1.5,
      "qed_min_used": 0.0,
      "pains_used": true
    }
  }
]
```
</details>

## Counterfactual suggestions (filtered)
_Rows below are generated from Tier 1 — Flip (relaxation: none)._ 
<table>
<tr><th>Rank</th><th>Structure</th><th>Tier</th><th>Relaxation</th><th>Similarity</th><th>p(toxic)</th><th>Δp</th><th>LogP</th><th>QED</th><th>SA</th></tr>
<tr><td>1</td><td><img src="cf_01.png" width="260"></td><td>Tier 1 — Flip</td><td>none</td><td>0.243</td><td>0.396</td><td>0.163</td><td>1.16</td><td>0.84</td><td>4.44</td></tr>
<tr><td>2</td><td><img src="cf_02.png" width="260"></td><td>Tier 1 — Flip</td><td>none</td><td>0.275</td><td>0.427</td><td>0.131</td><td>1.72</td><td>0.91</td><td>3.78</td></tr>
<tr><td>3</td><td><img src="cf_03.png" width="260"></td><td>Tier 1 — Flip</td><td>none</td><td>0.309</td><td>0.427</td><td>0.131</td><td>1.12</td><td>0.85</td><td>3.82</td></tr>
<tr><td>4</td><td><img src="cf_04.png" width="260"></td><td>Tier 1 — Flip</td><td>none</td><td>0.296</td><td>0.427</td><td>0.131</td><td>1.00</td><td>0.88</td><td>3.98</td></tr>
<tr><td>5</td><td><img src="cf_05.png" width="260"></td><td>Tier 1 — Flip</td><td>none</td><td>0.323</td><td>0.427</td><td>0.131</td><td>0.87</td><td>0.86</td><td>4.13</td></tr>
</table>

## Dataset-derived analogues (fallback)
_Nearest analogues from the dataset (context only, not generated edits)._ 
<table>
<tr><th>Rank</th><th>Structure</th><th>Similarity</th><th>p(toxic)</th><th>Δp</th><th>LogP</th><th>QED</th><th>SA</th><th>Alerts</th><th>Actionable?</th></tr>
<tr><td>1</td><td><img src="ds_01.png" width="260"></td><td>0.462</td><td>0.659</td><td>-0.101</td><td>2.87</td><td>0.73</td><td>3.50</td><td>⚠</td><td>NO</td></tr>
</table>
Fallback analogues are context-only; none meet feasibility constraints.

## Raw records (for audit)
### Counterfactuals JSON
```json
[
  {
    "raw_smiles": "C=C1C(=CCC#N)OC(C)(C)[C@H](O)[C@H]1N(C)S(=O)(=O)CC",
    "smiles": "C=C1C(=CCC#N)OC(C)(C)[C@H](O)[C@H]1N(C)S(=O)(=O)CC",
    "similarity": 0.24285714285714285,
    "p": 0.39562248764441715,
    "delta_p": 0.16307689312623325,
    "logp": 1.1599799999999998,
    "qed": 0.840611098842631,
    "sascore": 4.443349973120933,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "none",
    "relaxation_desc": "baseline constraints",
    "p_raw": 0.39562248764441715,
    "delta_p_raw": 0.16307689312623325,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CCS(=O)(=O)N(C)[C@H]1c2cc(C#N)cc(C)c2OC(C)(C)[C@@H]1O",
    "smiles": "CCS(=O)(=O)N(C)[C@H]1c2cc(C#N)cc(C)c2OC(C)(C)[C@@H]1O",
    "similarity": 0.2753623188405797,
    "p": 0.4274583483195352,
    "delta_p": 0.13124103245111518,
    "logp": 1.7212,
    "qed": 0.9060330021730634,
    "sascore": 3.782453817970289,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "none",
    "relaxation_desc": "baseline constraints",
    "p_raw": 0.4274583483195352,
    "delta_p_raw": 0.13124103245111518,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CCS(=O)(=O)N(C)[C@H]1c2cc(C#N)c(O)cc2OC(C)(C)[C@@H]1O",
    "smiles": "CCS(=O)(=O)N(C)[C@H]1c2cc(C#N)c(O)cc2OC(C)(C)[C@@H]1O",
    "similarity": 0.3088235294117647,
    "p": 0.4274583483195352,
    "delta_p": 0.13124103245111518,
    "logp": 1.1183800000000002,
    "qed": 0.8527939897680525,
    "sascore": 3.816713817970289,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "none",
    "relaxation_desc": "baseline constraints",
    "p_raw": 0.4274583483195352,
    "delta_p_raw": 0.13124103245111518,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CCS(=O)(=O)N(C)[C@H]1c2cc(CC#N)ncc2OC(C)(C)[C@@H]1O",
    "smiles": "CCS(=O)(=O)N(C)[C@H]1c2cc(CC#N)ncc2OC(C)(C)[C@@H]1O",
    "similarity": 0.29577464788732394,
    "p": 0.4274583483195352,
    "delta_p": 0.13124103245111518,
    "logp": 1.00218,
    "qed": 0.8775887985128038,
    "sascore": 3.9844468822830255,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "none",
    "relaxation_desc": "baseline constraints",
    "p_raw": 0.4274583483195352,
    "delta_p_raw": 0.13124103245111518,
    "tier_raw": "flip",
    "tier_num_std": 4,
    "tier_label_std": "diagnostic_close_edits"
  },
  {
    "raw_smiles": "CCS(=O)(=O)N(C)[C@H]1c2c[nH]cc2OC(C)(C)[C@@H]1O",
    "smiles": "CCS(=O)(=O)N(C)[C@H]1c2c[nH]cc2OC(C)(C)[C@@H]1O",
    "similarity": 0.3225806451612903,
    "p": 0.4274583483195352,
    "delta_p": 0.13124103245111518,
    "logp": 0.8691999999999998,
    "qed": 0.8642958864729703,
    "sascore": 4.13143006544405,
    "alert": false,
    "tier": "diagnostic_close_edits",
    "tier_label": "Tier 1 \u2014 Flip",
    "relaxation": "none",
    "relaxation_desc": "baseline constraints",
    "p_raw": 0.4274583483195352,
    "delta_p_raw": 0.13124103245111518,
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
    "raw_smiles": "CN([C@@H]1c2cc(OCCCC(F)(F)F)ccc2OC(C)(C)[C@H]1O)S(C)(=O)=O",
    "smiles": "CN([C@@H]1c2cc(OCCCC(F)(F)F)ccc2OC(C)(C)[C@H]1O)S(C)(=O)=O",
    "similarity": 0.46153846153846156,
    "p": 0.6593423663724483,
    "delta_p": -0.10064298560179785,
    "logp": 2.872300000000001,
    "qed": 0.7288620522693042,
    "sascore": 3.4962921195105334,
    "sa_status": "ok",
    "actionable": false,
    "alert": true,
    "tier": "dataset_analogue",
    "tier_label": "Dataset analogue",
    "relaxation": "none",
    "relaxation_desc": "dataset fallback",
    "sa_max_used": 4.5,
    "pains_used": true
  }
]
```
