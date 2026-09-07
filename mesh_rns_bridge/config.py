import configparser
import logging
import os
import sys
from typing import Optional


class Config:
    """
    Gestor de configuración central para Mesh-RNS Bridge.
    Lee y valida los parámetros de config.ini.
    """
    
    def __init__(self, config_path: str = "/etc/mesh-rns-bridge/config.ini"):
        self.config_path = config_path
        self._config = configparser.ConfigParser()
        
        # Atributos MQTT
        self.mqtt_host: str = "localhost"
        self.mqtt_port: int = 1883
        self.mqtt_user: str = ""
        self.mqtt_password: str = ""
        self.mqtt_client_id: str = "mesh-rns-bridge"
        self.mqtt_topic_sub: str = "msh/2/c/#"
        self.mqtt_topic_pub: str = "msh/2/c/Bridge"
        self.mqtt_keepalive: int = 60

        # Atributos Reticulum
        self.rns_identity_path: str = "~/.reticulum/identities/bridge"
        self.rns_storage_path: str = "~/.reticulum"
        self.rns_destination_hash: Optional[str] = None
        self.rns_aspect: str = "bridge"
        self.rns_send_mode: str = "packet"
        self.rns_link_timeout: int = 15

        # Atributos Filter
        self.filter_forward_text: bool = True
        self.filter_forward_telemetry: bool = False
        self.filter_forward_position: bool = False
        self.filter_forward_nodeinfo: bool = True
        self.filter_min_position_interval_sec: int = 300
        self.filter_min_telemetry_interval_sec: int = 300

        # Atributos Batching
        self.batching_enabled: bool = False
        self.batching_window_seconds: float = 1.5
        self.batching_max_buffered_packets: int = 10
        
        # Atributos Logging
        self.log_level_str: str = "INFO"
        self.log_to_file: bool = False
        self.log_path: str = "/var/log/mesh-rns-bridge/bridge.log"

    def load(self) -> None:
        """Carga y valida el archivo de configuración."""
        if not os.path.exists(self.config_path):
            logging.error(f"Archivo de configuracion no encontrado en: {self.config_path}")
            sys.exit(1)
            
        try:
            self._config.read(self.config_path)
            
            # [mqtt]
            if "mqtt" in self._config:
                self.mqtt_host = self._config["mqtt"].get("host", self.mqtt_host)
                self.mqtt_port = self._config["mqtt"].getint("port", self.mqtt_port)
                self.mqtt_user = self._config["mqtt"].get("user", self.mqtt_user)
                self.mqtt_password = self._config["mqtt"].get("password", self.mqtt_password)
                self.mqtt_client_id = self._config["mqtt"].get("client_id", self.mqtt_client_id)
                self.mqtt_topic_sub = self._config["mqtt"].get("topic_sub", self.mqtt_topic_sub)
                self.mqtt_topic_pub = self._config["mqtt"].get("topic_pub", self.mqtt_topic_pub)
                self.mqtt_keepalive = self._config["mqtt"].getint("keepalive", self.mqtt_keepalive)

            # [reticulum]
            if "reticulum" in self._config:
                self.rns_identity_path = self._config["reticulum"].get("identity_path", self.rns_identity_path)
                self.rns_storage_path = self._config["reticulum"].get("storage_path", self.rns_storage_path)
                self.rns_destination_hash = self._config["reticulum"].get("destination_hash", self.rns_destination_hash)
                self.rns_aspect = self._config["reticulum"].get("aspect", self.rns_aspect)
                self.rns_send_mode = self._config["reticulum"].get("send_mode", self.rns_send_mode).lower()
                self.rns_link_timeout = self._config["reticulum"].getint("link_timeout", self.rns_link_timeout)
                
            # [filter]
            if "filter" in self._config:
                self.filter_forward_text = self._config["filter"].getboolean("forward_text", self.filter_forward_text)
                self.filter_forward_telemetry = self._config["filter"].getboolean("forward_telemetry", self.filter_forward_telemetry)
                self.filter_forward_position = self._config["filter"].getboolean("forward_position", self.filter_forward_position)
                self.filter_forward_nodeinfo = self._config["filter"].getboolean("forward_nodeinfo", self.filter_forward_nodeinfo)
                self.filter_min_position_interval_sec = self._config["filter"].getint("min_position_interval_sec", self.filter_min_position_interval_sec)
                self.filter_min_telemetry_interval_sec = self._config["filter"].getint("min_telemetry_interval_sec", self.filter_min_telemetry_interval_sec)
                
            # [batching]
            if "batching" in self._config:
                self.batching_enabled = self._config["batching"].getboolean("enabled", self.batching_enabled)
                self.batching_window_seconds = self._config["batching"].getfloat("window_seconds", self.batching_window_seconds)
                self.batching_max_buffered_packets = self._config["batching"].getint("max_buffered_packets", self.batching_max_buffered_packets)
                
            # [logging]
            if "logging" in self._config:
                self.log_level_str = self._config["logging"].get("level", self.log_level_str).upper()
                self.log_to_file = self._config["logging"].getboolean("log_to_file", self.log_to_file)
                self.log_path = self._config["logging"].get("log_path", self.log_path)
                
        except configparser.Error as e:
            logging.error(f"Error parseando archivo de configuracion: {e}")
            sys.exit(1)
            
    def setup_logging(self) -> None:
        """Configura el sistema de logs (archivo y consola)."""
        numeric_level = getattr(logging, self.log_level_str, logging.INFO)
        
        handlers = [logging.StreamHandler(sys.stdout)]
        
        if self.log_to_file:
            log_dir = os.path.dirname(self.log_path)
            if log_dir and not os.path.exists(log_dir):
                try:
                    os.makedirs(log_dir, exist_ok=True)
                except OSError as e:
                    print(f"Advertencia: No se pudo crear el directorio de logs '{log_dir}': {e}")
            
            try:
                handlers.append(logging.FileHandler(self.log_path))
            except OSError as e:
                print(f"Advertencia: No se pudo escribir en el archivo de log '{self.log_path}': {e}")
                
        logging.basicConfig(
            level=numeric_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
