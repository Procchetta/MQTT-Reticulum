import os
import sys
import json
import time
import hashlib
import configparser
import threading
import RNS
import msgpack
import paho.mqtt.client as mqtt

# Load config
config = configparser.ConfigParser()
config.read('config.ini')

MQTT_HOST = config['MQTT'].get('BROKER_HOST', 'localhost')
MQTT_PORT = config['MQTT'].getint('BROKER_PORT', 1883)
MQTT_TOPIC_SUB = config['MQTT'].get('TOPIC_SUB', 'msh/2/c/#')

REMOTE_DEST_HASH_STR = config['RETICULUM'].get('REMOTE_DESTINATION_HASH', '')

# Filtering Configurations
ALLOW_ROUTING = config['FILTERING'].getboolean('ALLOW_ROUTING', fallback=False)
ALLOW_TELEMETRY = config['FILTERING'].getboolean('ALLOW_TELEMETRY', fallback=False)
ALLOW_UNKNOWN_APPS = config['FILTERING'].getboolean('ALLOW_UNKNOWN_APPS', fallback=False)

POS_RATE_LIMIT = config['FILTERING'].getint('POSITION_RATE_LIMIT_SEC', fallback=300)
NODEINFO_RATE_LIMIT = config['FILTERING'].getint('NODEINFO_RATE_LIMIT_SEC', fallback=3600)
DEDUP_CACHE_SEC = config['FILTERING'].getint('DEDUPLICATION_CACHE_SEC', fallback=600)

APP_NAME = "mqtt_mesh_bridge"
rns_destination = None

# Caches
msg_cache = {}  # { hash: timestamp }
app_throttle = {
    "POSITION_APP": {}, # { node_id: timestamp }
    "NODEINFO_APP": {}
}
cache_lock = threading.Lock()

def clean_caches():
    """Removes old entries from caches to prevent memory leaks."""
    now = time.time()
    with cache_lock:
        # Cleanup msg dedup cache
        keys_to_del = [k for k, v in msg_cache.items() if now - v > DEDUP_CACHE_SEC]
        for k in keys_to_del:
            del msg_cache[k]
        
        # Cleanup throttle caches (keep if within 2x their limit)
        for app in app_throttle.keys():
            limit = POS_RATE_LIMIT if app == "POSITION_APP" else NODEINFO_RATE_LIMIT
            keys_to_del = [k for k, v in app_throttle[app].items() if now - v > limit * 2]
            for k in keys_to_del:
                del app_throttle[app][k]

def rns_packet_callback(data, packet):
    """Called when an RNS packet is received from the remote bridge."""
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
            
        print(f"[RNS -> MQTT] Rcvd packet, publishing to {topic}")
        mqtt_client.publish(topic, mqtt_data)
        
    except msgpack.exceptions.UnpackException:
        print("[RNS] Error: Recibió un paquete que no es msgpack válido.")
    except Exception as e:
        print(f"[RNS] Error processing incoming packet: {e}")

def on_mqtt_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected with result code {rc}")
    client.subscribe(MQTT_TOPIC_SUB)
    print(f"[MQTT] Subscribed to {MQTT_TOPIC_SUB}")

def on_mqtt_message(client, userdata, msg):
    """Called when a Meshtastic message is received from local MQTT."""
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
        
        # ---- FILTRADO DURO (Hard blocks) ----
        if portnum == "ROUTING_APP" and not ALLOW_ROUTING:
            return
        if portnum == "TELEMETRY_APP" and not ALLOW_TELEMETRY:
            return
        if portnum == "UNKNOWN_APP" and not ALLOW_UNKNOWN_APPS:
            # Drop messages without a recognized portnum structure if disallowed
            return
            
        # ---- FILTRADO DE TASA (Throttling) ----
        if portnum in app_throttle:
            now = time.time()
            limit = POS_RATE_LIMIT if portnum == "POSITION_APP" else NODEINFO_RATE_LIMIT
            
            with cache_lock:
                last_time = app_throttle[portnum].get(sender_id, 0)
                if now - last_time < limit:
                    # Silently drop rate-limited packet
                    return
                app_throttle[portnum][sender_id] = now
                
        # ---- ENVÍO RNS ----
        if not REMOTE_DEST_HASH_STR:
            return
            
        rns_payload = {
            "t": msg.topic,
            "d": payload_str
        }
        
        rns_data = msgpack.packb(rns_payload, use_bin_type=True)
        print(f"[MQTT -> RNS] Sending {portnum} to remote over RNS ({len(rns_data)} bytes)")
        
        try:
            packet = RNS.Packet(rns_destination, rns_data)
            packet.send()
        except ValueError as e:
            print(f"[RNS] Warning: Packet too large for RNS single frame. ({len(rns_data)} bytes). Dropped.")
            
    except json.JSONDecodeError:
        pass 
    except Exception as e:
        print(f"[MQTT] Error handling message: {e}")

if __name__ == "__main__":
    print("Iniciando MQTT-Reticulum Bridge (Con Filtros Avanzados)...")
    
    reticulum = RNS.Reticulum()
    identity = RNS.Identity()
    
    local_destination = RNS.Destination(identity, RNS.Destination.IN, RNS.Destination.SINGLE, APP_NAME, "bridge")
    local_destination.set_packet_callback(rns_packet_callback)
    
    print("\n" + "="*50)
    print(f"Identidad Reticulum Local Hash: {RNS.hexrep(local_destination.hash, delimit=False)}")
    print("="*50 + "\n")
    
    if REMOTE_DEST_HASH_STR:
        print(f"Destino Remoto configurado: {REMOTE_DEST_HASH_STR}")
        try:
            remote_hash_bytes = bytes.fromhex(REMOTE_DEST_HASH_STR)
            remote_identity_req = RNS.Identity.recall(remote_hash_bytes)
            rns_destination = RNS.Destination(None, RNS.Destination.OUT, RNS.Destination.SINGLE, APP_NAME, "bridge")
            rns_destination.hash = remote_hash_bytes
        except Exception as e:
            print(f"Error configurando destino remoto: {e}")
            sys.exit(1)
    else:
        print("NOTA: No hay un REMOTE_DESTINATION_HASH en config.ini. Solo modo escucha.")
        
    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    except Exception as e:
        print(f"Error conectando a MQTT Broker en {MQTT_HOST}:{MQTT_PORT} -> {e}")
        sys.exit(1)
        
    mqtt_client.loop_start()
    
    try:
        while True:
            time.sleep(10)
            clean_caches()
    except KeyboardInterrupt:
        print("Cerrando puente...")
        mqtt_client.loop_stop()
        sys.exit(0)
