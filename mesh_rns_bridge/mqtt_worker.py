import logging
import time
import threading
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from mesh_rns_bridge.config import Config

logger = logging.getLogger(__name__)

class MQTTWorker:
    """
    Trabajador que gestiona la conexión MQTT, la suscripción y recepción de mensajes.
    Incluye lógica de reconexión automática y notificaciones mediante callbacks.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.client = mqtt.Client(client_id=self.config.mqtt_client_id)
        
        # Callback para cuando llega un mensaje: func(topic: str, payload_str: str)
        self.on_message_callback: Optional[Callable[[str, str], None]] = None
        
        # Configurar auth si existe
        if self.config.mqtt_user and self.config.mqtt_password:
            self.client.username_pw_set(self.config.mqtt_user, self.config.mqtt_password)
            
        # Callbacks de Paho
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        
    def _on_connect(self, client, userdata, flags, rc) -> None:
        """Callback al conectar al Broker MQTT."""
        if rc == 0:
            logger.info(f"Conectado a MQTT Broker en {self.config.mqtt_host}:{self.config.mqtt_port}")
            # Suscripción
            self.client.subscribe(self.config.mqtt_topic_sub)
            logger.info(f"Suscrito al tópico: {self.config.mqtt_topic_sub}")
        else:
            logger.error(f"Error conectando a MQTT. Código de retorno: {rc}")
            
    def _on_disconnect(self, client, userdata, rc) -> None:
        """Callback al desconectar del Broker MQTT."""
        if rc != 0:
            logger.warning(f"Desconexión inesperada de MQTT (rc: {rc}). Intentando reconectar...")
            
    def _on_message(self, client, userdata, msg) -> None:
        """Callback al recibir un mensaje del Broker MQTT."""
        try:
            payload_str = msg.payload.decode('utf-8')
            topic = msg.topic
            
            if self.on_message_callback:
                self.on_message_callback(topic, payload_str)
                
        except UnicodeDecodeError:
            logger.warning(f"Mensaje no-UTF8 recibido en {msg.topic}. Descartando.")
        except Exception as e:
            logger.error(f"Error procesando mensaje MQTT entrante: {e}")

    def start(self) -> None:
        """Inicia el cliente MQTT y su loop de red en background."""
        logger.info("Iniciando MQTT Worker...")
        try:
            self.client.connect(
                self.config.mqtt_host, 
                self.config.mqtt_port, 
                self.config.mqtt_keepalive
            )
            # El loop_start levanta su propio thread
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Excepción al conectar con el Broker MQTT: {e}")
            raise

    def stop(self) -> None:
        """Detiene el cliente MQTT limpiamente."""
        logger.info("Deteniendo MQTT Worker...")
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic: str, payload_str: str) -> None:
        """
        Publica un mensaje hacia el Broker MQTT.
        
        Args:
            topic: Tópico de destino.
            payload_str: Carga útil en formato string.
        """
        try:
            self.client.publish(topic, payload_str, qos=0)
            logger.debug(f"Publicado a MQTT en {topic}")
        except Exception as e:
            logger.error(f"Error publicando en MQTT ({topic}): {e}")
