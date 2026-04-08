# Lower-Similarity Completion Summary

This summary covers the scientifically critical lower-similarity portion of the existing ChEMBL Cluster pilot. It is based on the merged pilot outputs under [generation/run/lead_reports](/Users/harisreedeth/Desktop/Ogoing.hERGBench/hERGBench/reports/lead_opt_literature_audit_chembl/cluster_pilot/generation/run/lead_reports) plus the merged audit outputs under [tables](/Users/harisreedeth/Desktop/Ogoing.hERGBench/hERGBench/reports/lead_opt_literature_audit_chembl/cluster_pilot/tables).

## Scope

- Dataset: `chembl`
- Split: `cluster`
- Threshold: `0.710`
- Parent panel: existing 20-parent blocker panel only
- Targeted low-similarity bins in this phase:
  - `<0.3`
  - `0.3-0.5`

The already-known early successful parent [`a20f74e3f8ebfea51b2477906e00b06b1ca1e4b7`](/Users/harisreedeth/Desktop/Ogoing.hERGBench/hERGBench/reports/lead_opt_literature_audit_chembl/cluster_pilot/generation/run/lead_reports/a20f74e3f8ebfea51b2477906e00b06b1ca1e4b7/report.md) belongs to `0.5-0.7`, not to either lower-similarity bin.

## Targeted Lower-Similarity Parents

### `<0.3`

- `b53d5d72d6a789017275eb7570a60c2fbb91feb8`
- `fed009dbfb11625a971ea56dc6327d725e225cf5`
- `cb5c22de0ccdcf673936f4c8d07dfbd3f9a4aebb`
- `6dccdc2a597b0cc6a47a610c20ceb29232c73608`
- `86fcc24492f4309bcb809ceb104d043f0175ba1b`

### `0.3-0.5`

- `f1e739712c4f137b4f35c4a464d73a86510c2f4b`
- `bc119b6e181cb262689f3789e09ebd2d7fe97cc6`
- `32b0f4dc11d720f6d562a905d73c461574baf552`
- `637679562b622db5d3e779df2b670d634e37618d`
- `f9b723494f62a056148857a25337c48eaa4638ef`

## Completion Status

Both lower-similarity shards are now complete.

- `<0.3`: attempted `5`, completed `5`
- `0.3-0.5`: attempted `5`, completed `5`

No partial parent directories remained in either shard at completion.

## Outcome Counts By Similarity Bin

### `<0.3`

- Tier 1: `0`
- Tier 2: `0`
- Tier 3: `0`
- Tier 4 / diagnostic-only: `5`
- No-hit: `0`

### `0.3-0.5`

- Tier 1: `0`
- Tier 2: `0`
- Tier 3: `0`
- Tier 4 / diagnostic-only: `5`
- No-hit: `0`

### Higher-similarity comparison

- `0.5-0.7`: Tier 1 `4`, Tier 2 `0`, Tier 3 `0`, Tier 4 `1`
- `>0.7`: Tier 1 `5`, Tier 2 `0`, Tier 3 `0`, Tier 4 `0`

## Scaffold-Preserving Successful Candidates

- `<0.3`: none found in the reportable Tier 1-3 cohort
- `0.3-0.5`: none found in the reportable Tier 1-3 cohort
- `0.5-0.7`: yes; the retained best-per-parent successful candidates were scaffold-preserving
- `>0.7`: yes; the retained best-per-parent successful candidates were scaffold-preserving

Important interpretation boundary:
- this does **not** mean the low-similarity search space contained no scaffold-preserving molecules at all
- it means none of the completed low-similarity parents yielded surviving Tier 1-3 best-per-parent candidates under the existing scientific filters and audit cohort

## Literature-Concordance Comparison

The merged audit summary shows:

- `<0.3`: no retained Tier 1-3 best-per-parent candidates; no populated concordance row
- `0.3-0.5`: no retained Tier 1-3 best-per-parent candidates; no populated concordance row
- `0.5-0.7`: `4` best-per-parent retained candidates, mean concordance score `2.0`, literature-concordant overall `25%`
- `>0.7`: `5` best-per-parent retained candidates, mean concordance score `2.0`, literature-concordant overall `0%`

So the low-similarity bins do not merely have worse concordance scores. They fail earlier: they do not produce reportable Tier 1-3 best-per-parent survivors at all in this 20-parent pilot.

## Decision

The novelty-conditioned actionability question is now answerable at a coarse decision level.

Answer:
- yes, actionability appears to collapse below `0.5` train-similarity in this ChEMBL Cluster pilot
- all `10/10` completed low-similarity parents ended as Tier 4 diagnostic-only
- meanwhile the higher-similarity bins produced `9` reportable Tier 1 flips across `10` parents

What is **not** yet answerable well:
- a within-success comparison of scaffold-preserving success rates across all four bins
- a within-success comparison of literature-concordance in the two lower-similarity bins

Reason:
- both low-similarity bins contributed `0` retained Tier 1-3 best-per-parent candidates to the audit cohort

## Recommendation

Do **not** expand to all splits yet.

Recommended next step:
- stay on `cluster`
- selectively expand the lower-similarity regime before any all-split replication
- add another `5` parents in `<0.3`
- add another `5` parents in `0.3-0.5`

Rationale:
- the current 20-parent pilot is sufficient to show a likely low-similarity actionability collapse
- it is not yet sufficient to characterize *how* the surviving low-similarity successes, if any, differ in scaffold preservation or literature concordance
- scarcity itself is already an informative result, but a larger low-similarity cluster panel is needed before moving to Scaffold or Random replication
