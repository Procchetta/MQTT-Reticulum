# MQTT-Reticulum Bridge para Meshtastic 🌉

**Por Pablo Rocchetta (HP1PAR)**

Un puente inteligente bidireccional diseñado para conectar "islas" o mallas de **Meshtastic** geográficamente separadas utilizando el enrutamiento de **Reticulum Network Stack (RNS)**. 

Este proyecto permite extender redes de Meshtastic a través de enlaces de muy bajo ancho de banda, alta latencia y propensos a pérdidas (como módems LoRa de largo alcance, radios HF o packet radio) donde los enlaces TCP/IP tradicionales y VPNs convencionales fallarían.

## 🚀 Características Principales

- **Transparencia Total**: Los nodos de Meshtastic no notan la diferencia. Simplemente se conectan a un broker MQTT local; el puente captura los paquetes y los inyecta en la malla remota como si estuvieran en la misma habitación.
- **Firewall Inteligente de Tráfico**: Filtra por defecto la telemetría y las ruidosas tablas de enrutamiento local de Meshtastic (`ROUTING_APP`, `TELEMETRY_APP`), garantizando que por el enlace lento de Reticulum solo viaje la información vital.
- **Throttling (Límites de Tasa)**: Limita la transmisión de ubicaciones GPS (ej. 1 cada 5 minutos por nodo) y datos de hardware (`NODEINFO_APP`) para conservar el valioso ancho de banda de radiofrecuencia.
- **Protección Anti-Loops**: Caché criptográfica SHA-256 incorporada que detecta y elimina rebotes y paquetes duplicados, evitando "tormentas de broadcast" entre mallas.
- **Compresión MsgPack**: Serializa los pesados archivos JSON de Meshtastic a un formato binario altamente comprimido antes de enviarlos por Reticulum.

## 🛠️ Requisitos Previos

El instalador automático se encarga de casi todo, pero está diseñado preferentemente para sistemas basados en Debian (Raspberry Pi OS, Ubuntu, Debian):
- Python 3
- Servidor Mosquitto (El instalador lo provee automáticamente)

## 📦 Instalación Rápida (Recomendado)

En la máquina que actuará como puente (Raspberry Pi, Mini PC, etc.), descarga o clona este repositorio y ejecuta el script de instalación:

```bash
sudo ./install.sh
```

El script interactivo instalará **Mosquitto**, el entorno de Python, todas las dependencias y creará un servicio `systemd` para que el puente arranque de manera automática.

Durante la instalación se te preguntará por el **Hash Remoto**. Si estás instalando el primer nodo y aún no tienes el hash del segundo, puedes presionar `Enter` para dejarlo en blanco temporalmente.

## ⚙️ Configuración y Enlace

Para que el túnel funcione, el **Nodo A** necesita conocer el Hash de Reticulum del **Nodo B**, y viceversa.

1. Averigua tu **Hash Local** revisando los logs del servicio recién instalado:
   ```bash
   journalctl -u mqtt-reticulum.service -f
   ```
   *Busca una línea que diga: `Identidad Reticulum Local Hash: <TU_HASH>`*

2. Intercambia los hashes con la otra estación.
3. Edita el archivo `config.ini` y pega el hash de la otra estación en `REMOTE_DESTINATION_HASH`:
   ```bash
   nano config.ini
   ```
4. Aplica los cambios reiniciando el servicio:
   ```bash
   sudo systemctl restart mqtt-reticulum
   ```

### Ajuste de Filtros (`config.ini`)
Dentro del archivo de configuración puedes modificar qué pasa y qué no pasa por el puente:
- `ALLOW_ROUTING`: Por defecto `False`.
- `ALLOW_TELEMETRY`: Por defecto `False`.
- `POSITION_RATE_LIMIT_SEC`: Segundos entre envíos de GPS por nodo.
- `NODEINFO_RATE_LIMIT_SEC`: Segundos entre envíos de nombres de usuario.

## 🔮 Roadmap (Próximas Versiones)
- [ ] **Network Awareness (Fallback Inteligente)**: Sistema dinámico capaz de medir la latencia del enlace (RTT) directamente desde la API de Reticulum. Se incorporará un parámetro `FILTERING_AUTO = True|False` junto con umbrales configurables (ej. `RTT_CONTINGENCY_SEC = 2.5`) en el `config.ini`. Si está activo y el RTT está por debajo del umbral, el sistema deshabilitará los filtros temporalmente. Si el RTT supera el límite (ej. el tráfico pasa a radios LoRa/HF de respaldo), el puente aplicará el bloqueo estricto automáticamente.

---
*Desarrollado para comunicaciones resilientes y operaciones de emergencia (EmComm).*
