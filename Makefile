MODEL_ROOT ?= $(HOME)/models
MODEL_ID ?= OpenVINO/Qwen3-8B-int4-ov
OVMS_PORT ?= 4444
QSR_UI_PORT ?= 8600
QSR_UI_HOST ?= 0.0.0.0
SDK_REF ?= mcp
QSR_SAD_MCP_URL ?=
QSR_CALLBACK_URL ?=
HERMES_INSTALL_COMMIT ?=
QSR_CA_CERT_FILE ?= $(shell if [ -f .env ]; then sed -n 's/^QSR_CA_CERT_FILE=//p' .env | tail -n 1; fi)
QSR_EXTRA_CA_CERT_B64 = $(shell if [ -n "$(QSR_CA_CERT_FILE)" ] && [ -r "$(QSR_CA_CERT_FILE)" ]; then base64 "$(QSR_CA_CERT_FILE)" | tr -d '\n'; fi)
QSR_UV_ARCHIVE ?= $(shell if [ -f .env ]; then sed -n 's/^QSR_UV_ARCHIVE=//p' .env | tail -n 1; fi)
QSR_UV_BUILD_PATH = $(if $(strip $(QSR_UV_ARCHIVE)),.build/qsr-uv.tar.gz,docker/uv-placeholder.txt)
QSR_UV_PREBUILT = $(if $(strip $(QSR_UV_ARCHIVE)),true,false)
HOST_UID ?= $(shell id -u)
HOST_GID ?= $(shell id -g)
RENDER_DEVICE ?= $(firstword $(wildcard /dev/dri/renderD*))
RENDER_GID ?= $(shell if [ -n "$(RENDER_DEVICE)" ]; then stat -c '%g' "$(RENDER_DEVICE)"; else echo 992; fi)

export MODEL_ROOT MODEL_ID OVMS_PORT QSR_UI_PORT QSR_UI_HOST SDK_REF
export QSR_SAD_MCP_URL QSR_CALLBACK_URL HERMES_INSTALL_COMMIT QSR_EXTRA_CA_CERT_B64
export QSR_UV_BUILD_PATH QSR_UV_PREBUILT
export HOST_UID HOST_GID RENDER_GID

.PHONY: check prepare-build-assets build up down restart logs status

check:
	@command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
	@docker info >/dev/null || { echo "Docker daemon is not available to this user" >&2; exit 1; }
	@test -n "$(RENDER_DEVICE)" -a -e "$(RENDER_DEVICE)" || { echo "No Intel render device found at /dev/dri/render*" >&2; exit 1; }
	@test -f "$(MODEL_ROOT)/$(MODEL_ID)/config.json" || { echo "Model missing: $(MODEL_ROOT)/$(MODEL_ID)/config.json. Download it first or set MODEL_ROOT/MODEL_ID." >&2; exit 1; }
	@if [ -n "$(QSR_CA_CERT_FILE)" ] && [ ! -r "$(QSR_CA_CERT_FILE)" ]; then echo "CA certificate is not readable: $(QSR_CA_CERT_FILE)" >&2; exit 1; fi
	@if [ -n "$(QSR_UV_ARCHIVE)" ] && [ ! -r "$(QSR_UV_ARCHIVE)" ]; then echo "uv archive is not readable: $(QSR_UV_ARCHIVE)" >&2; exit 1; fi
	@docker compose version >/dev/null

prepare-build-assets:
	@if [ -n "$(QSR_UV_ARCHIVE)" ]; then mkdir -p .build && cp "$(QSR_UV_ARCHIVE)" .build/qsr-uv.tar.gz; fi

build: check prepare-build-assets
	docker compose build qsr-agent

up: check prepare-build-assets
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