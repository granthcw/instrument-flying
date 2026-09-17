# KJYO forecast backtest.
# `make help` lists every target.

PY      ?= python3
VENV    ?= .venv
BIN     := $(VENV)/bin
DATE    ?= $(shell date -u -d yesterday +%Y-%m-%d)
SITE    ?=
SITEARG := $(if $(SITE),--site $(SITE),)

.DEFAULT_GOAL := help
.PHONY: help venv install migrate test lint collect collect-dry-run \
        ingest-day backfill report thunder-check heartbeat clean

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

venv:  ## Create the virtualenv
	$(PY) -m venv $(VENV)

install: venv  ## Install dependencies
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r requirements.txt

migrate:  ## Apply database migrations (needs DATABASE_URL)
	@test -n "$$DATABASE_URL" || { echo "DATABASE_URL is not set (see .env.example)"; exit 1; }
	@for f in db/migrations/*.sql; do echo "applying $$f"; psql "$$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f $$f; done

test:  ## Run unit tests
	$(BIN)/pytest -q || PYTHONPATH=src $(PY) -m pytest -q

lint:  ## Byte-compile everything as a syntax check
	PYTHONPATH=src $(PY) -m compileall -q src tests

collect:  ## Pull the forecast under test and store raw + parsed rows
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli collect-forecast

collect-dry-run:  ## Pull without writing -- use this to verify a new API key
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli collect-forecast --dry-run

ingest-day:  ## Ingest one UTC day of observations and baselines (DATE=YYYY-MM-DD)
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli ingest-metar --date $(DATE) $(SITEARG)
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli ingest-glm   --date $(DATE) $(SITEARG)
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli ingest-mrms  --date $(DATE) $(SITEARG)
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli ingest-mos   --date $(DATE) $(SITEARG)
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli ingest-spc   --date $(DATE) $(SITEARG)

backfill:  ## Backfill a date range (START=YYYY-MM-DD END=YYYY-MM-DD)
	@test -n "$(START)" -a -n "$(END)" || { echo "usage: make backfill START=2025-05-01 END=2025-09-30"; exit 1; }
	@d="$(START)"; while [ "$$d" != "$$(date -u -d "$(END) +1 day" +%Y-%m-%d)" ]; do \
	   $(MAKE) --no-print-directory ingest-day DATE=$$d SITE=$(SITE) || exit 1; \
	   d=$$(date -u -d "$$d +1 day" +%Y-%m-%d); done

thunder-check:  ## Census TS/VCTS in a site's METAR archive
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli thunder-check $(SITEARG) \
	  $(if $(START),--start $(START),) $(if $(END),--end $(END),)

report:  ## Render reports/kjyo_backtest.html
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli report

heartbeat:  ## Run the daily health check
	PYTHONPATH=src $(PY) -m kjyo_backtest.cli heartbeat

clean:  ## Remove build and test artefacts
	rm -rf $(VENV) .pytest_cache reports/*.html
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
