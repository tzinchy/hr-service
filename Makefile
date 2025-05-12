.PHONY: run

run:
	cd auth_service && uv run uvicorn main:app --reload --port 8001