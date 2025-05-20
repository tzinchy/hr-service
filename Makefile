# Имя файла: Makefile

COMPOSE=docker-compose

.PHONY: up down restart logs ps build

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down -v --remove-orphans

restart:
	$(COMPOSE) down -v --remove-orphans
	$(COMPOSE) build --no-cache
	$(COMPOSE) up --force-recreate

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build --no-cache
