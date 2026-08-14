#!/bin/bash

# Asegurarse de que el script se ejecuta como root (o usa sudo)
if [ "$EUID" -ne 0 ]; then
  echo "Por favor ejecuta este instalador con sudo: sudo ./install.sh"
  exit
fi

echo "============================================="
echo " Instalador MQTT-Reticulum Bridge"
echo "============================================="

# 1. Instalar dependencias del sistema operativo
echo ">> Instalando Mosquitto y dependencias de Python..."
apt-get update
apt-get install -y mosquitto mosquitto-clients python3 python3-venv python3-pip

# 2. Configurar el entorno virtual e instalar los paquetes de python
echo ">> Configurando el entorno de Python..."
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -r requirements.txt

# 3. Menú de Configuración
echo "============================================="
echo " Configuración Inicial"
echo "============================================="
echo "Nota: Si es la primera vez que instalas, puedes dejar el Hash Remoto en blanco."
echo "Luego de iniciar por primera vez, el sistema te mostrará tu Hash Local para que lo compartas."
read -p "Ingresa el Hash de Reticulum del Nodo Remoto (dejar en blanco si no lo tienes aún): " remote_hash

if [ ! -f "config.ini" ]; then
cat <<EOF > config.ini
[MQTT]
BROKER_HOST = localhost
BROKER_PORT = 1883
TOPIC_SUB = msh/2/c/#
TOPIC_PUB_ROOT = msh/2/c

[RETICULUM]
REMOTE_DESTINATION_HASH = $remote_hash

[FILTERING]
ALLOW_ROUTING = False
ALLOW_TELEMETRY = False
ALLOW_UNKNOWN_APPS = False
POSITION_RATE_LIMIT_SEC = 300
NODEINFO_RATE_LIMIT_SEC = 3600
DEDUPLICATION_CACHE_SEC = 600
EOF
else
    # Update solo si se ingresó algo usando sed simple
    if [ -n "$remote_hash" ]; then
        sed -i "s/REMOTE_DESTINATION_HASH =.*/REMOTE_DESTINATION_HASH = $remote_hash/g" config.ini
    fi
fi

# 4. Crear Servicio Systemd
echo ">> Configurando el servicio Systemd para auto-arranque..."
SERVICE_FILE="/etc/systemd/system/mqtt-reticulum.service"

cat <<EOF > $SERVICE_FILE
[Unit]
Description=MQTT Reticulum Bridge for Meshtastic
After=network.target mosquitto.service

[Service]
Type=simple
User=root
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python $DIR/bridge.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mosquitto
systemctl start mosquitto
systemctl enable mqtt-reticulum
systemctl start mqtt-reticulum

echo "============================================="
echo " Instalación Completada exitosamente."
echo " Mosquitto y MQTT-Reticulum están corriendo en segundo plano."
echo " - Para ver los logs del puente y obtener tu HASH LOCAL, ejecuta:"
echo "     journalctl -u mqtt-reticulum.service -f"
echo ""
echo " - Para reconfigurar el hash remoto más tarde, edita config.ini y reinicia el servicio:"
echo "     nano $DIR/config.ini"
echo "     sudo systemctl restart mqtt-reticulum"
echo "============================================="
