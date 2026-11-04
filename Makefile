PYTHON ?= python
CONFIG ?= config/settings.yaml

.PHONY: data extract signals eval app test clean

data:
	$(PYTHON) -m src.generator.run --config $(CONFIG)

extract:
	$(PYTHON) -m src.extraction.pipeline --config $(CONFIG)

signals:
	$(PYTHON) -m src.indicators.run --config $(CONFIG)

eval:
	$(PYTHON) -m src.evaluation.signals_eval --config $(CONFIG)

app:
	@echo "make app: Этап 3 (UI), ещё не реализовано"; exit 1

test:
	$(PYTHON) -m pytest

clean:
	rm -rf data/synthetic/* .pytest_cache
