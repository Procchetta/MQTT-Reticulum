#!/bin/bash
# Uninstall script for Mesh-RNS Bridge

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Por favor, ejecute este script como root (sudo ./uninstall.sh)"
  exit 1
fi

echo "Deteniendo y deshabilitando servicio Systemd..."
systemctl stop mesh-rns-bridge.service || true
systemctl disable mesh-rns-bridge.service || true
rm -f /etc/systemd/system/mesh-rns-bridge.service
systemctl daemon-reload

echo "Eliminando archivos de la aplicación..."
rm -rf /opt/mesh-rns-bridge

echo "Nota: El directorio de configuración /etc/mesh-rns-bridge y los logs en /var/log/mesh-rns-bridge no han sido eliminados por seguridad."
echo "Si desea eliminarlos manualmente ejecute:"
echo "rm -rf /etc/mesh-rns-bridge /var/log/mesh-rns-bridge"

echo "Desinstalación completada."
