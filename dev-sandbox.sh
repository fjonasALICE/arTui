#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
SANDBOX_ROOT="${SANDBOX_ROOT:-$REPO_ROOT/.dev-sandboxes}"
SANDBOX_NAME=""
CONFIG_SOURCE=""
RECREATE=0
NO_LAUNCH=0
ARTUI_ARGS=()

usage() {
  cat <<'EOF'
Create and run an isolated ArTui development sandbox.

Usage:
  ./dev-sandbox.sh [options] [-- <extra artui args>]

Options:
  --name <name>             Sandbox name (default: timestamp-based)
  --sandbox-root <path>     Where sandboxes are created
                            (default: ./.dev-sandboxes)
  --config-source <path>    Copy this YAML file to sandbox config.yaml
  --python <bin>            Python executable for venv creation (default: python3)
  --recreate                Delete and recreate this sandbox if it exists
  --no-launch               Prepare sandbox but do not start artui
  -h, --help                Show this help

Examples:
  ./dev-sandbox.sh --name null-filters
  ./dev-sandbox.sh --name case1 --config-source /tmp/case1.yaml
  ./dev-sandbox.sh --name case2 -- --theme textual-dark
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      SANDBOX_NAME="${2:-}"
      shift 2
      ;;
    --sandbox-root)
      SANDBOX_ROOT="${2:-}"
      shift 2
      ;;
    --config-source)
      CONFIG_SOURCE="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --recreate)
      RECREATE=1
      shift
      ;;
    --no-launch)
      NO_LAUNCH=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      ARTUI_ARGS=("$@")
      break
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$SANDBOX_NAME" ]]; then
  SANDBOX_NAME="sandbox-$(date +%Y%m%d-%H%M%S)"
fi

SANDBOX_DIR="${SANDBOX_ROOT%/}/$SANDBOX_NAME"
VENV_DIR="$SANDBOX_DIR/.venv"
USER_DIR="$SANDBOX_DIR/user-data"
CONFIG_FILE="$USER_DIR/config.yaml"

if [[ $RECREATE -eq 1 && -d "$SANDBOX_DIR" ]]; then
  rm -rf "$SANDBOX_DIR"
fi

mkdir -p "$SANDBOX_DIR" "$USER_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install -U pip >/dev/null
"$VENV_DIR/bin/pip" install -e "$REPO_ROOT" >/dev/null

if [[ -n "$CONFIG_SOURCE" ]]; then
  if [[ ! -f "$CONFIG_SOURCE" ]]; then
    echo "Config source does not exist: $CONFIG_SOURCE" >&2
    exit 1
  fi
  cp "$CONFIG_SOURCE" "$CONFIG_FILE"
elif [[ ! -f "$CONFIG_FILE" ]]; then
  cat > "$CONFIG_FILE" <<'EOF'
feed_retention_days: 30
categories:
  HEP Phenomenology: hep-ph
filters: {}
EOF
fi

echo "Sandbox ready:"
echo "  sandbox:  $SANDBOX_DIR"
echo "  venv:     $VENV_DIR"
echo "  user-dir: $USER_DIR"
echo "  config:   $CONFIG_FILE"
echo
echo "Validate config:"
echo "  $VENV_DIR/bin/artui --user-dir \"$USER_DIR\" config validate"
echo

if [[ $NO_LAUNCH -eq 1 ]]; then
  exit 0
fi

exec "$VENV_DIR/bin/artui" --user-dir "$USER_DIR" "${ARTUI_ARGS[@]}"
