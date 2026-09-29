-include .env

MODEL_ROOT ?= $(HOME)/models
MODEL_ID ?= OpenVINO/Qwen3-8B-int4-ov
OVMS_PORT ?= 4444
QSR_UI_PORT ?= 8600
QSR_UI_HOST ?= 0.0.0.0
SDK_REF ?= mcp
QSR_SAD_MCP_URL ?=
QSR_CALLBACK_URL ?=
HERMES_INSTALL_COMMIT ?=
HOST_UID ?= $(shell id -u)
HOST_GID ?= $(shell id -g)
RENDER_DEVICE ?= $(firstword $(wildcard /dev/dri/renderD*))
RENDER_GID ?= $(shell if [ -n "$(RENDER_DEVICE)" ]; then stat -c '%g' "$(RENDER_DEVICE)"; else echo 992; fi)

export MODEL_ROOT MODEL_ID OVMS_PORT QSR_UI_PORT QSR_UI_HOST SDK_REF
export QSR_SAD_MCP_URL QSR_CALLBACK_URL HERMES_INSTALL_COMMIT
export HOST_UID HOST_GID RENDER_GID

.PHONY: init-env check build build-ready up up-ready down restart logs status

init-env:
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example"; fi

check:
	@command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
	@docker info >/dev/null || { echo "Docker daemon is not available to this user" >&2; exit 1; }
	@test -n "$(RENDER_DEVICE)" -a -e "$(RENDER_DEVICE)" || { echo "No Intel render device found at /dev/dri/render*" >&2; exit 1; }
	@test -f "$(MODEL_ROOT)/$(MODEL_ID)/config.json" || { echo "Model missing: $(MODEL_ROOT)/$(MODEL_ID)/config.json. Download it first or set MODEL_ROOT/MODEL_ID." >&2; exit 1; }
	@docker compose version >/dev/null

build: init-env
	$(MAKE) --no-print-directory build-ready

build-ready: check
	docker compose build qsr-agent

up: init-env
	$(MAKE) --no-print-directory up-ready

up-ready: check
	docker compose build qsr-agent
	docker compose up -d
	@echo "QSR Operator UI: http://localhost:$(QSR_UI_PORT)"

down:
	docker compose down

restart:
	docker compose restart qsr-agent

logs:
	docker compose logs -f --tail=100

status:
	docker compose ps