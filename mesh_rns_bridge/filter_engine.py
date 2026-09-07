import hashlib
import json
import logging
import threading
import time
from typing import Dict, Tuple

from mesh_rns_bridge.config import Config

logger = logging.getLogger(__name__)

class FilterEngine:
    """
    Motor de filtrado y deduplicación de mensajes.
    Previene bucles de eco entre MQTT y RNS y filtra tráfico innecesario.
    """
    
    def __init__(self, config: Config):
        self.config = config
        
        # Deduplicación: { sha256_hash: timestamp }
        self.msg_cache: Dict[str, float] = {}
        self.cache_lock = threading.Lock()
        
        # Rate Limiting: { app_name: { sender_id: timestamp } }
        self.app_throttle: Dict[str, Dict[str, float]] = {
            "POSITION_APP": {},
            "TELEMETRY_APP": {}
        }
        
        # Limpiar caché cada 5 minutos
        self.dedup_ttl = 300 
        
        # Demonio de limpieza
        self._running = True
        self._cleaner_thread = threading.Thread(target=self._clean_caches_loop, daemon=True)
        self._cleaner_thread.start()

    def _clean_caches_loop(self) -> None:
        """Hilo en background para limpiar las cachés periódicamente."""
        while self._running:
            time.sleep(60)
            now = time.time()
            with self.cache_lock:
                # Limpiar cache de hashes
                keys_to_del = [k for k, v in self.msg_cache.items() if now - v > self.dedup_ttl]
                for k in keys_to_del:
                    del self.msg_cache[k]
                
                # Limpiar throttle
                for app in self.app_throttle.keys():
                    limit = self.config.filter_min_position_interval_sec if app == "POSITION_APP" else self.config.filter_min_telemetry_interval_sec
                    # Usamos limit * 2 como TTL en la memoria para que el límite sea efectivo, luego lo borramos
                    keys_to_del = [k for k, v in self.app_throttle[app].items() if now - v > (limit * 2)]
                    for k in keys_to_del:
                        del self.app_throttle[app][k]

    def stop(self) -> None:
        """Detiene el hilo de limpieza de caché."""
        self._running = False

    def is_duplicate(self, data_str: str) -> bool:
        """
        Verifica si un string (JSON de MQTT) ya fue visto recientemente.
        Se usa tanto para mensajes recibidos por MQTT como los que llegan por RNS
        para evitar bucles.
        """
        data_hash = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
        
        with self.cache_lock:
            if data_hash in self.msg_cache:
                return True
            # Agregamos a la caché
            self.msg_cache[data_hash] = time.time()
            return False

    def should_forward_mqtt_to_rns(self, payload_str: str) -> bool:
        """
        Analiza el JSON recibido de MQTT (usualmente Meshtastic) y 
        determina si debe ser enviado a la red Reticulum (RNS)
        basado en la configuración (filtrado por portnum y rate limits).
        """
        try:
            data = json.loads(payload_str)
            payload_meta = data.get("payload", {})
            portnum = payload_meta.get("portnum", "UNKNOWN_APP")
            sender_id = data.get("from", "unknown")
            
            # 1. Filtros duros por tipo de aplicación
            if portnum == "TEXT_MESSAGE_APP" and not self.config.filter_forward_text:
                return False
            if portnum == "TELEMETRY_APP" and not self.config.filter_forward_telemetry:
                return False
            if portnum == "POSITION_APP" and not self.config.filter_forward_position:
                return False
            if portnum == "NODEINFO_APP" and not self.config.filter_forward_nodeinfo:
                return False
                
            # 2. Rate Limiting (Throttle)
            if portnum in self.app_throttle:
                now = time.time()
                limit = (self.config.filter_min_position_interval_sec 
                         if portnum == "POSITION_APP" 
                         else self.config.filter_min_telemetry_interval_sec)
                
                with self.cache_lock:
                    last_time = self.app_throttle[portnum].get(sender_id, 0)
                    if now - last_time < limit:
                        logger.debug(f"Descartando {portnum} de {sender_id} por límite de tasa ({limit}s).")
                        return False
                    # Actualizar timestamp
                    self.app_throttle[portnum][sender_id] = now
                    
            return True
            
        except json.JSONDecodeError:
            # Si no es JSON, lo pasamos bajo nuestro propio riesgo, 
            # pero ya Serializer lo atraparía o lo enviamos como opaco.
            # En base a la config actual asumimos que filtramos.
            return False
        except Exception as e:
            logger.error(f"Error evaluando filtros de mensaje: {e}")
            return False
