import os
import sys
import json
import time
import hashlib
import configparser
import threading
import logging
from logging.handlers import TimedRotatingFileHandler
import RNS
import msgpack
import paho.mqtt.client as mqtt

# ---------------------------------------------------------
# CONFIGURATION & LOGGING SETUP
# ---------------------------------------------------------
config = configparser.ConfigParser()
config.read('config.ini')

# Setup Logging
if not os.path.exists("LOGS"):
    os.makedirs("LOGS")

log_level_conf = config['LOGGING'].getint('LOG_LEVEL', fallback=1)
if log_level_conf == 3:
    py_log_level = logging.DEBUG
elif log_level_conf == 2:
    py_log_level = logging.WARNING
else:
    py_log_level = logging.INFO

log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_handler = TimedRotatingFileHandler("LOGS/bridge.log", when="midnight", interval=1, backupCount=7)
log_handler.setFormatter(log_formatter)
log_handler.suffix = "%Y-%m-%d"

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logger = logging.getLogger("Bridge")
logger.setLevel(py_log_level)
logger.addHandler(log_handler)
logger.addHandler(console_handler)

# Load basic configs
MQTT_HOST = config['MQTT'].get('BROKER_HOST', 'localhost')
MQTT_PORT = config['MQTT'].getint('BROKER_PORT', 1883)
MQTT_TOPIC_SUB = config['MQTT'].get('TOPIC_SUB', 'msh/2/c/#')
REMOTE_DEST_HASH_STR = config['RETICULUM'].get('REMOTE_DESTINATION_HASH', '')

# Autopilot configs
FILTERING_AUTO = config['AUTOPILOT'].getboolean('FILTERING_AUTO', fallback=True)
RTT_CONTINGENCY_SEC = config['AUTOPILOT'].getfloat('RTT_CONTINGENCY_SEC', fallback=2.5)
PING_INTERVAL_SEC = config['AUTOPILOT'].getint('PING_INTERVAL_SEC', fallback=30)

# Hard Fallback Filtering Configs
FALLBACK_ALLOW_ROUTING = config['FILTERING'].getboolean('ALLOW_ROUTING', fallback=False)
FALLBACK_ALLOW_TELEMETRY = config['FILTERING'].getboolean('ALLOW_TELEMETRY', fallback=False)
FALLBACK_ALLOW_UNKNOWN_APPS = config['FILTERING'].getboolean('ALLOW_UNKNOWN_APPS', fallback=False)
FALLBACK_POS_RATE = config['FILTERING'].getint('POSITION_RATE_LIMIT_SEC', fallback=300)
FALLBACK_NODEINFO_RATE = config['FILTERING'].getint('NODEINFO_RATE_LIMIT_SEC', fallback=3600)
DEDUP_CACHE_SEC = config['FILTERING'].getint('DEDUPLICATION_CACHE_SEC', fallback=600)

APP_NAME = "mqtt_mesh_bridge"
rns_destination = None

# ---------------------------------------------------------
# STATE & CACHES
# ---------------------------------------------------------
# Active filter states (Defaults to Contingency)
active_allow_routing = FALLBACK_ALLOW_ROUTING
active_allow_telemetry = FALLBACK_ALLOW_TELEMETRY
active_allow_unknown = FALLBACK_ALLOW_UNKNOWN_APPS
active_pos_rate = FALLBACK_POS_RATE
active_nodeinfo_rate = FALLBACK_NODEINFO_RATE
current_mode = "CONTINGENCY"

msg_cache = {}  # { hash: timestamp }
app_throttle = {
    "POSITION_APP": {},
    "NODEINFO_APP": {}
}
cache_lock = threading.Lock()

def clean_caches():
    now = time.time()
    with cache_lock:
        keys_to_del = [k for k, v in msg_cache.items() if now - v > DEDUP_CACHE_SEC]
        for k in keys_to_del:
            del msg_cache[k]
        
        for app in app_throttle.keys():
            limit = active_pos_rate if app == "POSITION_APP" else active_nodeinfo_rate
            keys_to_del = [k for k, v in app_throttle[app].items() if now - v > limit * 2]
            for k in keys_to_del:
                del app_throttle[app][k]

# ---------------------------------------------------------
# AUTOPILOT (NETWORK AWARENESS)
# ---------------------------------------------------------
def set_mode(mode):
    global current_mode, active_allow_routing, active_allow_telemetry, active_allow_unknown, active_pos_rate, active_nodeinfo_rate
    
    if mode == current_mode:
        return
        
    current_mode = mode
    if mode == "TRANSPARENT":
        logger.info(f">>> CAMBIO DE ESTADO: MODO TRANSPARENTE ACTIVO (RTT < {RTT_CONTINGENCY_SEC}s) <<<")
        active_allow_routing = True
        active_allow_telemetry = True
        active_allow_unknown = True
        active_pos_rate = 30 # Permissive GPS
        active_nodeinfo_rate = 120 # Permissive NodeInfo
    else:
        logger.info(f">>> CAMBIO DE ESTADO: MODO CONTINGENCIA ACTIVO (Usando config.ini fallback) <<<")
        active_allow_routing = FALLBACK_ALLOW_ROUTING
        active_allow_telemetry = FALLBACK_ALLOW_TELEMETRY
        active_allow_unknown = FALLBACK_ALLOW_UNKNOWN_APPS
        active_pos_rate = FALLBACK_POS_RATE
        active_nodeinfo_rate = FALLBACK_NODEINFO_RATE

def on_ping_delivery(receipt):
    try:
        rtt = receipt.get_rtt()
        logger.debug(f"[PING] Acuse recibido. RTT: {rtt:.3f}s")
        if rtt < RTT_CONTINGENCY_SEC:
            set_mode("TRANSPARENT")
        else:
            logger.warning(f"[PING] RTT alto detectado ({rtt:.3f}s >= {RTT_CONTINGENCY_SEC}s). Enlace degradado.")
            set_mode("CONTINGENCY")
    except Exception as e:
        logger.error(f"[PING] Error procesando acuse: {e}")
        set_mode("CONTINGENCY")

def on_ping_timeout(receipt):
    logger.warning("[PING] Timeout! El nodo remoto no respondio al ping a tiempo.")
    set_mode("CONTINGENCY")

def ping_daemon():
    while True:
        try:
            time.sleep(PING_INTERVAL_SEC)
            if FILTERING_AUTO and rns_destination:
                logger.debug("[PING] Enviando ping a destino remoto...")
                ping_packet = RNS.Packet(rns_destination, b"p", create_receipt=True)
                receipt = ping_packet.send()
                receipt.set_timeout(RTT_CONTINGENCY_SEC + 5.0) # Espera razonable antes de timeout
                receipt.set_delivery_callback(on_ping_delivery)
                receipt.set_timeout_callback(on_ping_timeout)
        except Exception as e:
            logger.error(f"[PING Daemon] Error en ciclo de ping: {e}")
            set_mode("CONTINGENCY")

# ---------------------------------------------------------
# MQTT & RNS LOGIC
# ---------------------------------------------------------
def rns_packet_callback(data, packet):
    if data == b"p":
        # Es solo un ping de la V2, no hacemos nada (el Receipt se envía solo)
        return
        
    try:
        payload_dict = msgpack.unpackb(data, raw=False)
        topic = payload_dict.get('t')
        mqtt_data = payload_dict.get('d')
        
        if not topic or not mqtt_data:
            return
            
        data_hash = hashlib.sha256(mqtt_data.encode('utf-8')).hexdigest()
        with cache_lock:
            if data_hash in msg_cache:
                return
            msg_cache[data_hash] = time.time()
            
        logger.debug(f"[RNS -> MQTT] Rcvd packet, publishing to {topic}")
        mqtt_client.publish(topic, mqtt_data)
        
    except msgpack.exceptions.UnpackException:
        logger.error("[RNS] Error: Recibió un paquete que no es msgpack válido.")
    except Exception as e:
        logger.error(f"[RNS] Error processing incoming packet: {e}")

def on_mqtt_connect(client, userdata, flags, rc):
    logger.info(f"[MQTT] Connected with result code {rc}")
    client.subscribe(MQTT_TOPIC_SUB)
    logger.info(f"[MQTT] Subscribed to {MQTT_TOPIC_SUB}")

def on_mqtt_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode('utf-8')
        
        data_hash = hashlib.sha256(msg.payload).hexdigest()
        with cache_lock:
            if data_hash in msg_cache:
                return
            msg_cache[data_hash] = time.time()

        data = json.loads(payload_str)
        payload_meta = data.get("payload", {})
        portnum = payload_meta.get("portnum", "UNKNOWN_APP")
        sender_id = data.get("from", "unknown")
        
        # Hard blocks dynamic based on mode
        if portnum == "ROUTING_APP" and not active_allow_routing:
            return
        if portnum == "TELEMETRY_APP" and not active_allow_telemetry:
            return
        if portnum == "UNKNOWN_APP" and not active_allow_unknown:
            return
            
        # Throttling dynamic based on mode
        if portnum in app_throttle:
            now = time.time()
            limit = active_pos_rate if portnum == "POSITION_APP" else active_nodeinfo_rate
            
            with cache_lock:
                last_time = app_throttle[portnum].get(sender_id, 0)
                if now - last_time < limit:
                    logger.debug(f"[MQTT] Dropping {portnum} from {sender_id} (Rate limited: {limit}s)")
                    return
                app_throttle[portnum][sender_id] = now
                
        # Send via RNS
        if not REMOTE_DEST_HASH_STR:
            return
            
        rns_payload = {
            "t": msg.topic,
            "d": payload_str
        }
        
        rns_data = msgpack.packb(rns_payload, use_bin_type=True)
        logger.debug(f"[MQTT -> RNS] Sending {portnum} to remote over RNS ({len(rns_data)} bytes)")
        
        try:
            packet = RNS.Packet(rns_destination, rns_data)
            packet.send()
        except ValueError as e:
            logger.warning(f"[RNS] Warning: Packet too large for RNS single frame. ({len(rns_data)} bytes). Dropped.")
            
    except json.JSONDecodeError:
        pass 
    except Exception as e:
        logger.error(f"[MQTT] Error handling message: {e}")

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
if __name__ == "__main__":
    logger.info("="*50)
    logger.info("Iniciando MQTT-Reticulum Bridge V2.0")
    if FILTERING_AUTO:
        logger.info(f"Autopilot ENABLED. RTT Threshold: {RTT_CONTINGENCY_SEC}s")
    else:
        logger.info("Autopilot DISABLED. Usando filtros fijos de Contingencia.")
    logger.info("="*50)
    
    reticulum = RNS.Reticulum()
    identity = RNS.Identity()
    
    local_destination = RNS.Destination(identity, RNS.Destination.IN, RNS.Destination.SINGLE, APP_NAME, "bridge")
    local_destination.set_packet_callback(rns_packet_callback)
    
    # IMPORTANTE: Requerido para responder a los Pings con Acuses de Recibo
    local_destination.set_proof_strategy(RNS.Destination.PROVE_ALL)
    
    logger.info(f"Identidad Reticulum Local Hash: {RNS.hexrep(local_destination.hash, delimit=False)}")
    
    if REMOTE_DEST_HASH_STR:
        logger.info(f"Destino Remoto configurado: {REMOTE_DEST_HASH_STR}")
        try:
            remote_hash_bytes = bytes.fromhex(REMOTE_DEST_HASH_STR)
            remote_identity_req = RNS.Identity.recall(remote_hash_bytes)
            rns_destination = RNS.Destination(None, RNS.Destination.OUT, RNS.Destination.SINGLE, APP_NAME, "bridge")
            rns_destination.hash = remote_hash_bytes
            
            # Iniciar demonio de ping
            if FILTERING_AUTO:
                ping_th = threading.Thread(target=ping_daemon, daemon=True)
                ping_th.start()
                
        except Exception as e:
            logger.error(f"Error configurando destino remoto: {e}")
            sys.exit(1)
    else:
        logger.info("NOTA: No hay un REMOTE_DESTINATION_HASH en config.ini. Solo modo escucha.")
        
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    except Exception as e:
        logger.error(f"Error conectando a MQTT Broker en {MQTT_HOST}:{MQTT_PORT} -> {e}")
        sys.exit(1)
        
    mqtt_client.loop_start()
    
    try:
        while True:
            time.sleep(10)
            clean_caches()
    except KeyboardInterrupt:
        logger.info("Cerrando puente...")
        mqtt_client.loop_stop()
        sys.exit(0)
