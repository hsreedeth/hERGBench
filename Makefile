.PHONY: run run-fetch stage1 stage1-fast lint format

run:
	hergbench run -c configs/base.yaml

run-fetch:
	hergbench run -c configs/base.yaml --fetch-data

stage1:
	hergbench stage1 -c configs/stage1_mvp.yaml

stage1-fast:
	hergbench stage1 -c configs/stage1_mvp.yaml --skip-counterfactuals

lint:
	ruff check .

format:
	ruff check . --fix
