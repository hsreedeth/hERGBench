
<div align="center">
  <img src="https://i.postimg.cc/8PBt9zYM/h-ERGCOver.jpg" alt = "project hERG cover image" />
</div>


# hERG Bench
---

Cardiotoxicity mediated by hERG channel blockage is a critical failure mode in drug discovery. While machine learning models can predict hERG liability, their utility is often limited by (1) over-optimistic performance estimates derived from random data splitting, and (2) a lack of actionable guidance for medicinal chemists.

This project aims to build a production-grade predictive pipeline that rigorously benchmarks "out-of-distribution" generalization. We compare a strong structural baseline (XGBoost + ECFP) against a Graph Neural Network (D-MPNN) using a rigorous Triple-Split Protocol (Random, Scaffold, and Cluster). Furthermore, the pipeline moves beyond prediction to prescription by generating chemically valid, low-risk counterfactual analogues for toxic compounds, filtered for synthetic accessibility.



