#!/bin/bash
# Sube la central al servidor de AWS y la deja corriendo como servicio.
#   bash desplegar.sh                 sube codigo y reinicia
#   bash desplegar.sh --primera-vez   ademas instala python, cloudflared y los servicios
set -e
cd "$(dirname "$0")"
# La IP del servidor y la ruta de la llave SSH no van en el repo: se leen de ~/.sei/ip y ~/.sei/llave
IP=${SEI_IP:-$(cat ~/.sei/ip 2>/dev/null)}
LLAVE=${SEI_LLAVE:-$(cat ~/.sei/llave 2>/dev/null)}
[ -n "$IP" ] && [ -n "$LLAVE" ] || { echo "falta ~/.sei/ip o ~/.sei/llave"; exit 1; }
SSH="ssh -i $LLAVE -o ConnectTimeout=20 ubuntu@$IP"

echo "== subiendo codigo"
tar czf - --exclude=datos --exclude=__pycache__ --exclude='*.pyc' . | $SSH 'mkdir -p ~/sei && tar xzf - -C ~/sei'

if [ "$1" = "--primera-vez" ]; then
  CLAVE=$(powershell -NoProfile -c '[Environment]::GetEnvironmentVariable("SEI_CLAVE","User")' | tr -d '\r')
  TOKEN=$(cat ~/.sei/tunel_token)
  echo "== instalando"
  $SSH "CLAVE='$CLAVE' TOKEN='$TOKEN' bash -s" <<'REMOTO'
set -e
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv sqlite3 >/dev/null
python3 -m venv ~/sei/venv
~/sei/venv/bin/pip install -q flask waitress cryptography requests
sudo mkdir -p /etc/sei
echo "SEI_CLAVE=$CLAVE" | sudo tee /etc/sei/clave.env >/dev/null
sudo chmod 600 /etc/sei/clave.env

sudo tee /etc/systemd/system/sei-central.service >/dev/null <<EOF
[Unit]
Description=Central SEI
After=network-online.target
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/sei
EnvironmentFile=/etc/sei/clave.env
ExecStart=/home/ubuntu/sei/venv/bin/python app.py
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/sei-simulador.service >/dev/null <<EOF
[Unit]
Description=Simulador SEI (datos de demostracion hasta tener la radio)
After=sei-central.service
[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/sei
EnvironmentFile=/etc/sei/clave.env
ExecStart=/home/ubuntu/sei/venv/bin/python simulador.py --rapido 10
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF

if ! command -v cloudflared >/dev/null; then
  curl -sL -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo dpkg -i /tmp/cloudflared.deb >/dev/null
fi
sudo cloudflared service install "$TOKEN" >/dev/null 2>&1 || true
sudo systemctl daemon-reload
sudo systemctl enable --now sei-central sei-simulador cloudflared
REMOTO
fi

echo "== reiniciando"
$SSH 'sudo systemctl restart sei-central sei-simulador && sleep 3 && systemctl is-active sei-central sei-simulador cloudflared && curl -s -o /dev/null -w "local: %{http_code}\n" http://127.0.0.1:8160/api/resumen'
