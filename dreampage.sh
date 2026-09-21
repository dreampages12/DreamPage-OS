#!/usr/bin/env bash
# DreamPage OS - supervisoren paa Linux. Motstykket til dreampage.ps1.
#
#   ./dreampage.sh up        start ComfyUI, flow, mockup, bot, tunnel
#   ./dreampage.sh down      stopp alt vi eier (ikke midt i en ordre)
#   ./dreampage.sh status    hva lever, hva staar i koen, hvor er ordrene
#   ./dreampage.sh restart
#   ./dreampage.sh logs      foelg flow-loggen
#   ./dreampage.sh test      alle testene + check_assets + check_portability
#   ./dreampage.sh ensure    vaktmesteren (systemd-timer, hvert 5. minutt)
#   ./dreampage.sh mode      hva denne PC-en er til: book eller preview
#   ./dreampage.sh mode preview     bytt modus (krever restart)
#
# Selve logikken ligger i tools/dreampage.py, ikke her. Bash ville betydd en
# TREDJE utgave av helsesjekker og ventetider, i et spraak uten tester. Denne
# fila finner bare riktig Python og gir den argumentene videre.
#
# DP_PYTHON i miljoeet peker paa tolken - det er formen systemd vil ha naar
# DreamPage kjoerer i et virtuelt miljoe. Se docs/SETUP-LINUX.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Rekkefoelgen er bevisst: et venv I treet vinner over systemets python3, slik
# at avhengighetene som er pinnet i requirements.txt er de som faktisk kjoerer.
if [ -n "${DP_PYTHON:-}" ]; then
    PY="$DP_PYTHON"
elif [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    echo "fant ingen python3. Se docs/SETUP-LINUX.md" >&2
    exit 1
fi

exec "$PY" "$ROOT/tools/dreampage.py" "$@"
