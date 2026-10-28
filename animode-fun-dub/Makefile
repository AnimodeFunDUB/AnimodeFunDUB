.PHONY: install check ui api test lint
install:
	python -m pip install -e '.[test]'
check:
	python -m animode.preflight
ui:
	python -m animode.webui
api:
	python -m animode.api
test:
	python -m pytest tests/animode -q
lint:
	python -m ruff check animode dub_video.py scripts/inference/batch_process.py tests/animode
