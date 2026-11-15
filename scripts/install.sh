#!/usr/bin/env bash
# nanotok installer: installs the `nanotok` CLI so it is available on PATH.
#
# Strategy:
#   1. If pipx exists, install into an isolated pipx environment.
#   2. Otherwise, create an isolated venv under ~/.local/share/nanotok
#      and expose a launcher at ~/.local/bin/nanotok.
# This avoids PEP 668 "externally-managed-environment" failures on
# Debian/Ubuntu and never modifies the system Python.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/FerzDevZ/nanotok/main/scripts/install.sh | bash
#   bash scripts/install.sh [--from-git URL_OR_LOCAL_PATH] [--upgrade]
set -euo pipefail

REPO_URL="git+https://github.com/FerzDevZ/nanotok.git"
UPGRADE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --from-git)
      [ "$#" -ge 2 ] || { echo "Missing value for --from-git" >&2; exit 2; }
      REPO_URL="$2"; shift 2 ;;
    --upgrade)
      UPGRADE=1; shift ;;
    -h|--help)
      echo "Usage: install.sh [--from-git URL_OR_LOCAL_PATH] [--upgrade]"; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

if have nanotok && [ "$UPGRADE" -eq 0 ]; then
  echo "[nanotok] already installed: $(command -v nanotok)"
  nanotok --version || true
  echo "[nanotok] use --upgrade to reinstall/upgrade."
  exit 0
fi

install_with_pipx() {
  if [ "$UPGRADE" -eq 1 ]; then
    pipx install --force "${REPO_URL}"
  else
    pipx install "${REPO_URL}" || pipx install --force "${REPO_URL}"
  fi
  pipx ensurepath >/dev/null 2>&1 || true
}

install_with_venv() {
  local bin_dir="${HOME}/.local/bin"
  local data_dir="${XDG_DATA_HOME:-${HOME}/.local/share}/nanotok"
  local venv_dir="${data_dir}/venv"

  if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "[nanotok] python3-venv is unavailable; install it (e.g. 'sudo apt install python3-venv') or install pipx, then retry." >&2
    exit 1
  fi

  echo "[nanotok] creating isolated environment at ${venv_dir}"
  rm -rf "${venv_dir}"
  python3 -m venv "${venv_dir}"

  local pip_args=(install --quiet --disable-pip-version-check)
  if [ "$UPGRADE" -eq 1 ]; then
    pip_args+=(--force-reinstall)
  fi
  echo "[nanotok] installing from ${REPO_URL}"
  "${venv_dir}/bin/python" -m pip "${pip_args[@]}" "${REPO_URL}"

  mkdir -p "${bin_dir}"
  cat > "${bin_dir}/nanotok" <<EOF
#!/usr/bin/env bash
exec "${venv_dir}/bin/nanotok" "\$@"
EOF
  chmod +x "${bin_dir}/nanotok"
}

if have pipx; then
  echo "[nanotok] installing via pipx from ${REPO_URL}"
  install_with_pipx
else
  echo "[nanotok] pipx not found; using isolated venv fallback"
  install_with_venv
  PATH="${HOME}/.local/bin:${PATH}"
  export PATH
fi

hash -r 2>/dev/null || true

if have nanotok; then
  echo "[nanotok] installed successfully: $(command -v nanotok)"
  nanotok --version || true
  echo "[nanotok] you can now run: nanotok --help"
else
  echo "[nanotok] installed, but 'nanotok' is not on PATH yet."
  echo "[nanotok] open a new terminal or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo "[nanotok] then verify: nanotok --version"
fi
