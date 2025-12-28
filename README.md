# hERG Bench
---

Cardiotoxicity induced by hERG-protein mediated channel blockage is a common and well documented failure mode in drug discovery. Although machine learning models have made significant advancements in predictions associated with hERG liability, there are still limiatations why ?(i) over-optimistic model outputs primarily as a result of random data splitting & (ii) lack of actionable insights for chemists.

This project aims to build a production-grade predictive pipeline that rigorously benchmarks "out-of-distribution" generalization. We compare a strong structural baseline (XGBoost + ECFP) against a Graph Neural Network (D-MPNN) using a rigorous Triple-Split Protocol (Random, Scaffold, and Cluster). Furthermore, the pipeline moves beyond prediction to prescription by generating chemically valid, low-risk counterfactual analogues for toxic compounds, filtered for synthetic accessibility.



