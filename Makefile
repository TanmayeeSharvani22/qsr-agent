-include .env

MODEL_ROOT ?= $(CURDIR)/models
OVMS_PORT ?= 4444
QSR_UI_PORT ?= 8600
QSR_UI_HOST ?= 0.0.0.0
# Image source: REGISTRY=true (default) pulls the pre-built image; REGISTRY=false builds from source.
TAG ?= latest
REGISTRY ?= true
REGISTRY_URL ?= intel/
QSR_IMAGE ?= $(REGISTRY_URL)qsr-agent:$(TAG)
WEATHER_IMAGE ?= $(REGISTRY_URL)qsr-weather:$(TAG)
REGISTRY_LOWER := $(shell echo $(REGISTRY) | tr A-Z a-z)
HERMES_INSTALL_COMMIT ?=
HOST_UID ?= $(shell id -u)
HOST_GID ?= $(shell id -g)
WEATHER_PORT ?= 8090
RENDER_DEVICE ?= $(firstword $(wildcard /dev/dri/renderD*))
RENDER_GID ?= $(shell if [ -n "$(RENDER_DEVICE)" ]; then stat -c '%g' "$(RENDER_DEVICE)"; else echo 992; fi)
TAG ?= latest

export MODEL_ROOT MODEL_ID OVMS_PORT QSR_UI_PORT QSR_UI_HOST
export HERMES_INSTALL_COMMIT QSR_IMAGE WEATHER_IMAGE TAG
export HOST_UID HOST_GID RENDER_GID
export WEATHER_PORT
export TAG

.PHONY: init-env check build build-ready up up-ready down restart logs status download-models download-models-ready weather queue learn

init-env:
	@cp .env.example .env
	@echo "Refreshed .env from .env.example"

download-models: init-env
	$(MAKE) --no-print-directory download-models-ready

download-models-ready:
	bash download_models/model_download.sh

check:
	@command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
	@docker info >/dev/null || { echo "Docker daemon is not available to this user" >&2; exit 1; }
	@test -n "$(RENDER_DEVICE)" -a -e "$(RENDER_DEVICE)" || { echo "No Intel render device found at /dev/dri/render*" >&2; exit 1; }
	@test -n "$(MODEL_ID)" || { echo "MODEL_ID is not set; set it in .env.example" >&2; exit 1; }
	@test -f "$(MODEL_ROOT)/$(MODEL_ID)/config.json" || { echo "Model missing: $(MODEL_ROOT)/$(MODEL_ID)/config.json. Download it first or set MODEL_ROOT/MODEL_ID." >&2; exit 1; }
	@docker compose version >/dev/null

build: init-env
	$(MAKE) --no-print-directory build-ready

build-ready: check
	@if [ "$(REGISTRY_LOWER)" = "true" ]; then \
		echo "Pulling images $(QSR_IMAGE) and $(WEATHER_IMAGE) from registry..."; \
		docker compose pull qsr-agent weather; \
	else \
		echo "Building qsr-agent and weather images from source..."; \
		docker compose build qsr-agent weather; \
	fi

up: init-env
	$(MAKE) --no-print-directory up-ready

up-ready: check
	@if [ "$(REGISTRY_LOWER)" = "true" ]; then \
		echo "Pulling images $(QSR_IMAGE) and $(WEATHER_IMAGE) from registry..."; \
		docker compose pull qsr-agent weather; \
		docker compose up -d --no-build; \
	else \
		echo "Building qsr-agent and weather images from source..."; \
		docker compose build qsr-agent weather; \
		docker compose up -d; \
	fi
	@echo "QSR Operator UI: http://localhost:$(QSR_UI_PORT)"

down:
	docker compose down

restart:
	docker compose restart qsr-agent

logs:
	docker compose logs -f --tail=100

status:
	docker compose ps

# Demo weather: make weather CONDITION=rain TEMP=12 (add NO_EVENT=1 to stage silently).
weather:
	@test -n "$(CONDITION)" || { echo "Usage: make weather CONDITION=clear|cloudy|fog|drizzle|rain|storm|snow [TEMP=12] [NO_EVENT=1]" >&2; exit 1; }
	docker compose exec weather weather-simulator set "$(CONDITION)" $(if $(TEMP),--temperature "$(TEMP)") $(if $(NO_EVENT),--no-event)

# Demo queue: make queue COUNT=12 [WAIT=9] (add NO_EVENT=1 to stage silently).
queue:
	@test -n "$(COUNT)" || { echo "Usage: make queue COUNT=<customers> [WAIT=<minutes>] [NO_EVENT=1]" >&2; exit 1; }
	docker compose exec qsr-agent python scripts/queue_event.py --count "$(COUNT)" $(if $(WAIT),--wait "$(WAIT)") $(if $(NO_EVENT),--no-event)

# Operator-taught learning: make learn ARGS="setup|import FILE|status|run|pending|approve ID|reject ID|finalize".
learn:
	docker compose exec qsr-agent python scripts/learn.py $(or $(ARGS),status)
