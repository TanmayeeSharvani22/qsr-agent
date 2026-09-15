#!/usr/bin/env bash
# Uninstall the QSR stack installed by scripts/setup.sh: Hermes, the OVMS
# container, and the operator UI. Runs fully unattended (no prompts). Safe to
# run repeatedly.
#
# Usage:
#   scripts/uninstall.sh                 # remove Hermes + ~/.hermes + OVMS + UI
#   KEEP_DATA=1 scripts/uninstall.sh     # keep ~/.hermes (config/history)
#   KEEP_UV=1  scripts/uninstall.sh      # keep uv/uvx if bundled under ~/.hermes/bin
#   REMOVE_OVMS=0 scripts/uninstall.sh   # leave the OVMS container running
set -Eeuo pipefail

HERMES_HOME=${HERMES_HOME:-"$HOME/.hermes"}
BIN_DIR=${BIN_DIR:-"$HOME/.local/bin"}
OVMS_CONTAINER=${OVMS_CONTAINER:-ovms-qwen3-8b}
UI_PID_FILE=${UI_PID_FILE:-/tmp/qsr-operator-ui.pid}
KEEP_DATA=${KEEP_DATA:-0}
KEEP_UV=${KEEP_UV:-0}
# OVMS and the UI are removed by default; set REMOVE_OVMS=0 to keep OVMS.
REMOVE_OVMS=${REMOVE_OVMS:-1}

log() { printf '[hermes-uninstall] %s\n' "$*"; }

stop_processes() {
    log "Stopping Hermes processes"
    pkill -TERM -f 'hermes-agent/hermes' 2>/dev/null || true
    pkill -TERM -f "$HERMES_HOME/" 2>/dev/null || true
    sleep 2
    pkill -KILL -f 'hermes-agent/hermes' 2>/dev/null || true
    pkill -KILL -f "$HERMES_HOME/" 2>/dev/null || true
}

stop_operator_ui() {
    log "Stopping operator UI"
    if [[ -f "$UI_PID_FILE" ]]; then
        local pid; pid=$(cat "$UI_PID_FILE" 2>/dev/null || true)
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
        rm -f "$UI_PID_FILE"
    fi
    pkill -f 'operator-ui/app.py' 2>/dev/null || true
}

preserve_uv() {
    # Move uv/uvx out of ~/.hermes/bin into ~/.local/bin so they survive removal.
    [[ $KEEP_UV == 1 ]] || return 0
    local tool
    for tool in uv uvx; do
        if [[ -e "$HERMES_HOME/bin/$tool" && ! -e "$BIN_DIR/$tool" ]]; then
            log "Preserving $tool -> $BIN_DIR/$tool"
            cp -a "$HERMES_HOME/bin/$tool" "$BIN_DIR/$tool" 2>/dev/null || true
        fi
    done
}

remove_launchers() {
    log "Removing Hermes launchers from $BIN_DIR"
    rm -f "$BIN_DIR/hermes" "$BIN_DIR/hermes-acp" "$BIN_DIR/hermes-agent"
    # Only remove node/npm/npx if they are symlinks pointing into ~/.hermes.
    local link target
    for link in node npm npx; do
        target=$(readlink -f "$BIN_DIR/$link" 2>/dev/null || true)
        if [[ -L "$BIN_DIR/$link" && $target == "$HERMES_HOME"/* ]]; then
            log "Removing bundled $link symlink"
            rm -f "$BIN_DIR/$link"
        fi
    done
}

remove_data() {
    if [[ $KEEP_DATA == 1 ]]; then
        log "KEEP_DATA=1 set; leaving $HERMES_HOME in place"
        return 0
    fi
    if [[ -d "$HERMES_HOME" ]]; then
        log "Deleting $HERMES_HOME"
        rm -rf "$HERMES_HOME"
    fi
}

remove_ovms() {
    [[ $REMOVE_OVMS == 1 ]] || return 0
    command -v docker >/dev/null 2>&1 || { log "docker not found; skipping OVMS removal"; return 0; }
    if docker container inspect "$OVMS_CONTAINER" >/dev/null 2>&1; then
        log "Removing OVMS container $OVMS_CONTAINER"
        docker rm -f "$OVMS_CONTAINER" >/dev/null 2>&1 || true
    fi
}

verify() {
    log "Verifying removal"
    command -v hermes >/dev/null 2>&1 && log "WARNING: 'hermes' still on PATH at $(command -v hermes)" || log "hermes: not found (good)"
    [[ -d "$HERMES_HOME" ]] && [[ $KEEP_DATA != 1 ]] && log "WARNING: $HERMES_HOME still exists" || true
    if [[ $REMOVE_OVMS == 1 ]] && command -v docker >/dev/null 2>&1; then
        docker container inspect "$OVMS_CONTAINER" >/dev/null 2>&1 \
            && log "WARNING: OVMS container $OVMS_CONTAINER still exists" \
            || log "OVMS: removed (good)"
    fi
}

main() {
    stop_processes
    stop_operator_ui
    preserve_uv
    remove_launchers
    remove_data
    remove_ovms
    verify
    log "Done."
}

main "$@"
