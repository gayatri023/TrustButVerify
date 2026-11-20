.PHONY: setup test lint typecheck analyze validate-suite doctor clean demo docker-tests docs-html

setup:
	uv sync --all-extras

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy tbv

typecheck:
	uv run mypy tbv

analyze:
	uv run tbv analyze

validate-suite:
	uv run tbv suite validate

doctor:
	uv run tbv doctor

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist

demo:
	uv run tbv demo

docker-tests:
	uv run tbv sandbox build
	uv run pytest -q -m docker

docs-html:
	uv run python scripts/build_docs.py
