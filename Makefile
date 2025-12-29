.PHONY: run run-fetch lint format

run:
	python -m hergbench.cli run --config configs/base.yaml

run-fetch:
	python -m hergbench.cli run --config configs/base.yaml --fetch-data

lint:
	ruff check .

format:
	ruff check . --fix

