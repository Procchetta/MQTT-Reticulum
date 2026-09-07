import logging
import signal
import sys
import time

from mesh_rns_bridge.config import Config
from mesh_rns_bridge.filter_engine import FilterEngine
from mesh_rns_bridge.mqtt_worker import MQTTWorker
from mesh_rns_bridge.rns_worker import RNSWorker
from mesh_rns_bridge.serializer import Serializer

logger = logging.getLogger("MeshBridgeMain")

class MeshRNSBridge:
    """
    Clase principal que orquesta el MQTT Worker, el RNS Worker y el Filter Engine.
    """
    
    def __init__(self):
        self.config = Config()
        self.config.load()
        self.config.setup_logging()
        
        self.filter_engine = FilterEngine(self.config)
        self.mqtt_worker = MQTTWorker(self.config)
        self.rns_worker = RNSWorker(self.config)
        
        # Enlace de callbacks
        self.mqtt_worker.on_message_callback = self.handle_mqtt_message
        self.rns_worker.on_message_callback = self.handle_rns_message
        
        self.running = False

    def handle_mqtt_message(self, topic: str, payload_str: str) -> None:
        """Procesa mensajes que llegan desde MQTT (hacia RNS)."""
        # 1. Deduplicación
        if self.filter_engine.is_duplicate(payload_str):
            return
            
        # 2. Filtrado y Rate Limiting
        if not self.filter_engine.should_forward_mqtt_to_rns(payload_str):
            return
            
        # 3. Serialización a Binario
        rns_payload = Serializer.mqtt_to_rns(topic, payload_str)
        
        # 4. Enviar a RNS
        if rns_payload:
            self.rns_worker.send(rns_payload)

    def handle_rns_message(self, data_bytes: bytes) -> None:
        """Procesa mensajes que llegan desde RNS (hacia MQTT)."""
        # 1. Deserialización
        mqtt_data = Serializer.rns_to_mqtt(data_bytes)
        
        if not mqtt_data:
            return
            
        topic = mqtt_data["topic"]
        payload_str = mqtt_data["payload"]
        
        # 2. Deduplicación (para evitar reenviar a MQTT algo que nosotros mismos emitimos 
        # o evitar rebotes en redes complejas)
        if self.filter_engine.is_duplicate(payload_str):
            return
            
        # 3. Enviar a MQTT
        # Nota: Por defecto, inyectamos en el mismo tópico de subscripción,
        # o podríamos publicarlo en un tópico específico de Bridge configurado.
        self.mqtt_worker.publish(topic, payload_str)

    def start(self) -> None:
        """Inicia todos los workers."""
        logger.info("="*50)
        logger.info("Iniciando MQTT-Reticulum Bridge V2.0")
        logger.info("="*50)
        
        self.running = True
        
        # Iniciar stack RNS (puede tomar un instante si debe descubrir cosas locales)
        self.rns_worker.start()
        
        # Iniciar cliente MQTT
        self.mqtt_worker.start()

    def stop(self) -> None:
        """Detiene todos los workers de forma segura."""
        if not self.running:
            return
            
        logger.info("Apagando Mesh-RNS Bridge...")
        self.running = False
        
        self.mqtt_worker.stop()
        self.rns_worker.stop()
        self.filter_engine.stop()
        
        logger.info("Apagado completado.")


# Instancia global para poder acceder desde el handler de señales
bridge = None

def signal_handler(sig, frame):
    """Manejador de señales POSIX para shutdown elegante."""
    logger.info(f"Señal {sig} recibida, iniciando apagado...")
    if bridge:
        bridge.stop()
    sys.exit(0)

def main():
    global bridge
    
    # Registrar señales de sistema (Ctrl+C, o systemctl stop)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        bridge = MeshRNSBridge()
        bridge.start()
        
        # Mantener el proceso vivo en el hilo principal
        while bridge.running:
            time.sleep(1)
            
    except Exception as e:
        logger.critical(f"Falla crítica en el sistema: {e}", exc_info=True)
        if bridge:
            bridge.stop()
        sys.exit(1)

if __name__ == "__main__":
    main()
