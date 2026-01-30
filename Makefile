.PHONY: install dev redis run test clean db db-stop

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

run-aggregator:
	.venv/bin/python -m axtrade.aggregator

run-strategy:
	.venv/bin/python -m axtrade.strategies

run-api:
	.venv/bin/python -m axtrade.api.app

bars:
	.venv/bin/python -m axtrade.cli bars $(SYMBOL) --limit $(or $(LIMIT),10)

test:
	.venv/bin/pytest -v

clean:
	rm -rf .venv build *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
