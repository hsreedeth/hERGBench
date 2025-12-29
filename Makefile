.PHONY: run run-fetch lint format

run:
	hergbench --config configs/base.yaml

run-fetch:
	hergbench.cli --config configs/base.yaml --fetch-data

lint:
	ruff check .

format:
	ruff check . --fix

