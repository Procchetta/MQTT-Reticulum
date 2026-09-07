import json
import logging
from typing import Dict, Any, Optional
import msgpack

logger = logging.getLogger(__name__)

class Serializer:
    """
    Maneja la conversión entre JSON (MQTT) y Binario (RNS).
    Utiliza msgpack para una compresión eficiente del diccionario completo.
    """
    
    @staticmethod
    def mqtt_to_rns(topic: str, payload_str: str) -> Optional[bytes]:
        """
        Empaqueta el tópico y el payload de MQTT en un paquete binario msgpack.
        
        Args:
            topic: Tópico MQTT de origen.
            payload_str: String JSON con el contenido del mensaje.
            
        Returns:
            bytes: Paquete binario listo para enviar por RNS, o None en caso de error.
        """
        try:
            # Validamos que sea un JSON válido antes de empacar
            # para no gastar ancho de banda en basura
            json.loads(payload_str)
            
            rns_payload = {
                "t": topic,
                "d": payload_str
            }
            return msgpack.packb(rns_payload, use_bin_type=True)
            
        except json.JSONDecodeError:
            logger.warning("Mensaje MQTT no es un JSON válido. Descartando.")
            return None
        except Exception as e:
            logger.error(f"Error serializando mensaje MQTT a RNS: {e}")
            return None

    @staticmethod
    def rns_to_mqtt(data: bytes) -> Optional[Dict[str, str]]:
        """
        Desempaqueta un payload binario RNS (msgpack) a un diccionario 
        con tópico y datos string para MQTT.
        
        Args:
            data: Binario recibido por Reticulum.
            
        Returns:
            dict: Diccionario con 't' (topic) y 'd' (datos JSON en string), o None.
        """
        try:
            payload_dict = msgpack.unpackb(data, raw=False)
            
            if not isinstance(payload_dict, dict):
                return None
                
            topic = payload_dict.get('t')
            mqtt_data = payload_dict.get('d')
            
            if not topic or not mqtt_data:
                return None
                
            return {"topic": str(topic), "payload": str(mqtt_data)}
            
        except msgpack.exceptions.UnpackException:
            logger.error("Error: Se recibió un paquete por RNS que no es msgpack válido.")
            return None
        except Exception as e:
            logger.error(f"Error deserializando mensaje RNS a MQTT: {e}")
            return None
