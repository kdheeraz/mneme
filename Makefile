.PHONY: up down logs ps reset demo sdk-install api-shell db-shell

up:
	docker compose up --build -d
	@echo ""
	@echo "  API:        http://localhost:8000/docs"
	@echo "  Dashboard:  http://localhost:3000"
	@echo ""
	@echo "Tail logs:  make logs"

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

reset:
	docker compose down -v
	docker compose up --build -d

demo:
	pip install -e ./sdk-python httpx --quiet
	python examples/demo_agent.py

sdk-install:
	pip install -e ./sdk-python

api-shell:
	docker compose exec api bash

db-shell:
	docker compose exec db psql -U mneme -d mneme
