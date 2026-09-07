#!/bin/bash
# Install script for Mesh-RNS Bridge

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Por favor, ejecute este script como root (sudo ./install.sh)"
  exit 1
fi

APP_DIR="/opt/mesh-rns-bridge"
CONF_DIR="/etc/mesh-rns-bridge"
LOG_DIR="/var/log/mesh-rns-bridge"

echo "Instalando dependencias del sistema..."
apt-get update
apt-get install -y python3-venv python3-pip

echo "Creando directorios..."
mkdir -p "$APP_DIR"
mkdir -p "$CONF_DIR"
mkdir -p "$LOG_DIR"

echo "Configurando entorno virtual en $APP_DIR..."
python3 -m venv "$APP_DIR"

echo "Instalando paquete Mesh-RNS Bridge..."
# Instalamos la rueda/paquete local usando pip desde el venv
"$APP_DIR/bin/pip" install --upgrade pip wheel
"$APP_DIR/bin/pip" install .

echo "Copiando archivo de configuración..."
if [ ! -f "$CONF_DIR/config.ini" ]; then
    cp config.ini.example "$CONF_DIR/config.ini"
    echo "Plantilla de configuración copiada a $CONF_DIR/config.ini"
else
    echo "El archivo $CONF_DIR/config.ini ya existe. No se sobrescribirá."
fi

echo "Instalando servicio Systemd..."
cp systemd/mesh-rns-bridge.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable mesh-rns-bridge.service

echo ""
echo "=========================================================================="
echo "Instalación completada con éxito."
echo "1. Edite /etc/mesh-rns-bridge/config.ini con sus parámetros."
echo "2. Inicie el servicio con: sudo systemctl start mesh-rns-bridge.service"
echo "3. Vea los logs con: sudo journalctl -u mesh-rns-bridge.service -f"
echo "=========================================================================="
