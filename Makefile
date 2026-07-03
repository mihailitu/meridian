.PHONY: install dev redis run run-ibkr run-alpaca run-aggregator run-strategy run-api run-fulltest run-fulltest-download test test-integration clean db db-stop infra infra-stop setup build-ui

install:
	python3 -m venv .venv
	.venv/bin/pip install -e .

dev:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

redis:
	docker compose up -d redis

redis-stop:
	docker compose down redis

db:
	docker compose up -d timescaledb

db-stop:
	docker compose down timescaledb

infra:
	docker compose up -d

infra-stop:
	docker compose down

run:
	.venv/bin/python -m axtrade.gateway

run-ibkr:
	.venv/bin/python -m axtrade.gateway --adapter ibkr

run-alpaca:
	.venv/bin/python -m axtrade.gateway --adapter alpaca

run-yahoo:
	.venv/bin/python -m axtrade.gateway --adapter yahoo

run-aggregator:
	.venv/bin/python -m axtrade.aggregator

run-strategy:
	.venv/bin/python -m axtrade.strategies

run-api:
	.venv/bin/python -m axtrade.api.app

run-fulltest-download:
	.venv/bin/python -m axtrade.fulltest download $(ARGS)

run-fulltest:
	.venv/bin/python -m axtrade.fulltest run $(ARGS)

bars:
	.venv/bin/python -m axtrade.cli bars $(SYMBOL) --limit $(or $(LIMIT),10)

test:
	.venv/bin/pytest -v

test-integration:
	.venv/bin/pytest tests/integration -m integration -v

clean:
	rm -rf .venv build *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +

setup:
	./scripts/setup.sh

build-ui:
	cd src/axtrade/web/ui && npm run build
