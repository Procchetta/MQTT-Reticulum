# Mesh-RNS Bridge

**Desarrollo de código abierto para la comunidad CIPRO Panamá.**

Mesh-RNS Bridge es una solución modular de nivel de producción que permite interconectar brokers de MQTT (típicamente usados con dispositivos Meshtastic) a través del protocolo **Reticulum Network Stack (RNS)**. 
Permite establecer redes de malla de largo alcance o intercontinentales, filtrando inteligentemente la telemetría y enrutando los mensajes deseados usando bajo ancho de banda.

## Licenciamiento y Uso Comunitario

Este proyecto está bajo licencia **MIT**. Su uso es totalmente libre para fines experimentales, de emergencia y comunitarios. 

El único requerimiento para su distribución y uso es **preservar el reconocimiento y enlace al proyecto original de CIPRO Panamá**, promoviendo así la colaboración abierta y el desarrollo tecnológico solidario.

## Características

* **Cero variables hardcodeadas:** Configuración completa mediante `config.ini`.
* **Motor de Filtrado Inteligente:** Control granular para dejar pasar solo los paquetes deseados (Textos, Telemetría, Posición, NodeInfo) y proteger enlaces de bajo ancho de banda con límites de tasa (rate limiting).
* **Compresión msgpack:** Conversión binaria de alta eficiencia que reduce drásticamente el tamaño del payload sobre Reticulum.
* **Resiliencia MQTT:** Conexión y reconexión automática de Paho-MQTT, aislando fallas temporales.
* **Integración Systemd:** Operación como servicio daemon nativo en entornos Linux.

## Guía de Instalación Rápida

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/cipropanama/mesh-rns-bridge.git
   cd mesh-rns-bridge
   ```

2. **Ejecutar el instalador (como root):**
   ```bash
   sudo ./install.sh
   ```
   *Esto creará un entorno virtual en `/opt/mesh-rns-bridge`, instalará las dependencias y configurará el servicio en systemd.*

3. **Editar la configuración:**
   Abra `/etc/mesh-rns-bridge/config.ini` con su editor favorito y ajuste los parámetros (MQTT host, tópicos, opciones de filtrado, etc.).
   ```bash
   sudo nano /etc/mesh-rns-bridge/config.ini
   ```

4. **Levantar el servicio:**
   ```bash
   sudo systemctl start mesh-rns-bridge
   ```

   Puede verificar los logs en tiempo real con:
   ```bash
   sudo journalctl -u mesh-rns-bridge -f
   ```

## Configuración de Nodos Distantes (Destination Hash)

Para interconectar dos brokers distantes A y B usando Reticulum:

1. **Formato JSON:** Asegúrese de que el gateway de Meshtastic (o el nodo que inyecta datos al MQTT) tenga habilitada la salida en formato **JSON** si desea usar las opciones de filtrado granular (Telemetría, Posición, NodeInfo, etc.). De lo contrario, los paquetes binarios cifrados nativos serán ignorados por el puente para ahorrar ancho de banda.
2. **Hashes Remotos:** Para la prueba de campo, necesitará dos instancias corriendo, y tendrá que cruzar los `destination_hash` en el archivo `config.ini` de cada lado.
3. **Iniciar el Puente A:** Inicie el servicio en el primer servidor sin configurar `destination_hash`. Observe los logs para encontrar su *Hash Local*:
   ```
   Reticulum Listo. Hash Local (Escuchando): 9abc1234def56789...
   ```
4. **Iniciar el Puente B:** Inicie el servicio en el segundo servidor de igual manera para obtener su propio *Hash Local* (ej: `1234abcd5678...`).
5. **Cruzar los Hashes:** 
   - En el servidor A, edite `/etc/mesh-rns-bridge/config.ini` y establezca `destination_hash = 1234abcd5678...` (el hash del servidor B).
   - En el servidor B, establezca `destination_hash = 9abc1234def56789...` (el hash del servidor A).
6. **Reiniciar servicios:** Ejecute `sudo systemctl restart mesh-rns-bridge` en ambos extremos. El tráfico ahora fluirá bidireccionalmente según las reglas de filtrado establecidas.
