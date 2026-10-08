dev:
	docker compose up --build

test:
	cd backend && pytest

lint:
	cd frontend && npm run typecheck

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m scripts.seed

evaluate:
	cd backend && python scripts/evaluate.py
