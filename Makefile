PYTHON ?= python
CONFIG ?= config/settings.yaml

.PHONY: data extract signals eval eval-extract metrics app test clean

data:
	$(PYTHON) -m src.generator.run --config $(CONFIG)

extract:
	$(PYTHON) -m src.extraction.pipeline --config $(CONFIG)

signals:
	$(PYTHON) -m src.indicators.run --config $(CONFIG)

eval:
	$(PYTHON) -m src.evaluation.signals_eval --config $(CONFIG)

eval-extract:
	$(PYTHON) -m src.evaluation.extraction_eval --config $(CONFIG)

metrics:
	$(PYTHON) -m src.evaluation.report --full

app:
	$(PYTHON) -m streamlit run src/app/streamlit_app.py --server.headless true --server.address 0.0.0.0 --browser.gatherUsageStats false

test:
	$(PYTHON) -m pytest

clean:
	rm -rf data/synthetic/* .pytest_cache
