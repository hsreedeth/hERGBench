.PHONY: run run-fetch stage1 stage1-fast stage1-refreeze stage1-mvp stage1-mvp-fast lint format

# Default configs (override like: make stage1 STAGE1_CFG=... )
RUN_CFG ?= configs/base.yaml
STAGE1_CFG ?= configs/stage1_signoff.yaml
STAGE1_MVP_CFG ?= configs/stage1_mvp.yaml

run:
	hergbench run -c $(RUN_CFG)

run-fetch:
	hergbench run -c $(RUN_CFG) --fetch-data

# SAFE DEFAULT: triple-split signoff config
stage1:
	hergbench stage1 -c $(STAGE1_CFG)

stage1-fast:
	hergbench stage1 -c $(STAGE1_CFG) --skip-counterfactuals

# REFREEZE: always regenerate split membership files
stage1-refreeze:
	hergbench stage1 -c $(STAGE1_CFG) --force-resplit

# Keep MVP targets explicitly named (cluster-only iteration)
stage1-mvp:
	hergbench stage1 -c $(STAGE1_MVP_CFG)

stage1-mvp-fast:
	hergbench stage1 -c $(STAGE1_MVP_CFG) --skip-counterfactuals

lint:
	ruff check .

format:
	ruff check . --fix
