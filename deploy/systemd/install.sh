#!/usr/bin/env bash
# Installer vaktmesteren som en systemd-timer for DENNE brukeren.
#
#   ./deploy/systemd/install.sh
#
# Bruker-enheter, ikke system-enheter, og det er et valg: ComfyUI trenger
# GPU-tilgang og brukerens miljoe, og en system-enhet ville kjort som root
# med et annet HOME - da finner koden verken ~/.n8n, brukerens venv eller
# Tailscale-oekta.
#
# `loginctl enable-linger` er den ene tingen som er lett aa glemme: uten den
# stopper brukerens systemd naar den siste SSH-oekta lukkes, og da doer hele
# DreamPage naar du logger av. En server som stopper naar noen logger av er
# ikke en server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNITS="$HOME/.config/systemd/user"

if [ "$ROOT" != "$HOME/DreamPage-OS" ]; then
    echo "MERK: unit-filene bruker %h/DreamPage-OS, men repoet ligger i"
    echo "      $ROOT"
    echo "      Rett stiene i deploy/systemd/*.service|*.timer foerst, eller"
    echo "      legg repoet i \$HOME/DreamPage-OS."
    exit 1
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "fant ingen $ROOT/.venv/bin/python - se docs/SETUP-LINUX.md" >&2
    exit 1
fi

mkdir -p "$UNITS"
cp "$ROOT/deploy/systemd/dreampage-ensure.service" "$UNITS/"
cp "$ROOT/deploy/systemd/dreampage-ensure.timer" "$UNITS/"

systemctl --user daemon-reload
systemctl --user enable --now dreampage-ensure.timer

# Uten dette stopper alt naar du logger av.
if ! loginctl show-user "$USER" --property=Linger | grep -q "Linger=yes"; then
    echo
    echo "Slaar paa linger, slik at DreamPage lever videre etter utlogging:"
    sudo loginctl enable-linger "$USER"
fi

echo
systemctl --user list-timers dreampage-ensure.timer --no-pager
echo
echo "Vaktmesteren kjoerer naa hvert 5. minutt."
echo "  systemctl --user status dreampage-ensure.service"
echo "  journalctl --user -u dreampage-ensure -f"
echo "  tail -f $ROOT/state/watchdog.log"
