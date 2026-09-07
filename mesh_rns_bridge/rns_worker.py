import logging
import time
import queue
import threading
from typing import Callable, Optional, List

import RNS

from mesh_rns_bridge.config import Config

logger = logging.getLogger(__name__)


class RNSWorker:
    """
    Trabajador encargado de la red Reticulum (RNS).
    Maneja la identidad, anuncio, enlaces, recepción (Destination IN) y envío (Destination OUT).
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.reticulum: Optional[RNS.Reticulum] = None
        self.identity: Optional[RNS.Identity] = None
        
        self.local_destination: Optional[RNS.Destination] = None
        self.remote_destination: Optional[RNS.Destination] = None
        self.rns_link: Optional[RNS.Link] = None
        
        # Callback para cuando llega un mensaje desde RNS: func(data_bytes: bytes)
        self.on_message_callback: Optional[Callable[[bytes], None]] = None
        
        # Cola y thread para batching
        self._batch_queue: queue.Queue = queue.Queue()
        self._batching_active = True
        self._batch_thread = threading.Thread(target=self._batch_worker, daemon=True)
        
    def start(self) -> None:
        """Inicia el stack de Reticulum y configura los Destinos."""
        logger.info("Iniciando Reticulum Network Stack...")
        
        # Inicializa Reticulum con el path de configuración indicado
        self.reticulum = RNS.Reticulum(configdir=self.config.rns_storage_path)
        
        # Configurar Identidad
        if self.config.rns_identity_path and self.config.rns_identity_path != "":
            # RNS manejará la creación de la identidad si no existe internamente,
            # pero necesitamos proveerla explícitamente si queremos persistencia custom.
            # En V2 se prefiere dejar que RNS use su Default si no se pasa nada, o cargar de un file.
            pass 
        
        # Para mantener simpleza, usamos la identidad por defecto de este nodo
        self.identity = RNS.Identity()
        
        # 1. Configurar Destino Local (Para Escuchar)
        self.local_destination = RNS.Destination(
            self.identity, 
            RNS.Destination.IN, 
            RNS.Destination.SINGLE, 
            "mesh_bridge", 
            self.config.rns_aspect
        )
        self.local_destination.set_packet_callback(self._on_rns_packet)
        self.local_destination.set_link_established_callback(self._on_link_established)
        
        # Proveemos acuses de recibo para enlaces
        self.local_destination.set_proof_strategy(RNS.Destination.PROVE_ALL)
        
        local_hash = RNS.hexrep(self.local_destination.hash, delimit=False)
        logger.info(f"Reticulum Listo. Hash Local (Escuchando): {local_hash}")
        
        # 2. Configurar Destino Remoto (Para Enviar)
        if self.config.rns_destination_hash:
            logger.info(f"Configurando Destino Remoto: {self.config.rns_destination_hash}")
            try:
                remote_hash_bytes = bytes.fromhex(self.config.rns_destination_hash)
                
                # Para poder crear un Destino de SALIDA, en SINGLE mode, 
                # usualmente necesitamos recordar la identidad si usamos enlaces.
                # Para un Packet no encriptado no es estrictamente necesario, pero RNS lo pide para links.
                RNS.Identity.recall(remote_hash_bytes)
                
                self.remote_destination = RNS.Destination(
                    None, 
                    RNS.Destination.OUT, 
                    RNS.Destination.SINGLE, 
                    "mesh_bridge", 
                    self.config.rns_aspect
                )
                self.remote_destination.hash = remote_hash_bytes
                
                if self.config.rns_send_mode == "link":
                    self._establish_link()
                    
            except Exception as e:
                logger.error(f"Error configurando el destino remoto RNS: {e}")
        else:
            logger.info("NOTA: No se definió 'destination_hash' en config.ini. Operando solo en modo escucha.")
            
        # Iniciar thread de batching
        if self.config.batching_enabled:
            logger.info("Batching RNS activado.")
            self._batch_thread.start()

    def _establish_link(self) -> None:
        """Intenta establecer un enlace RNS si el modo es 'link'."""
        if not self.remote_destination:
            return
            
        logger.info("Intentando establecer enlace (Link) con destino remoto...")
        self.rns_link = RNS.Link(self.remote_destination)
        self.rns_link.set_link_closed_callback(self._on_link_closed)
        
        # Esperamos a que se establezca (bloqueante momentáneo)
        timeout = time.time() + self.config.rns_link_timeout
        while self.rns_link.status != RNS.Link.ACTIVE and time.time() < timeout:
            time.sleep(0.1)
            
        if self.rns_link.status == RNS.Link.ACTIVE:
            logger.info("Enlace RNS establecido exitosamente.")
        else:
            logger.warning("Timeout estableciendo enlace RNS. Los paquetes pueden fallar hasta que reconecte.")

    def _on_link_established(self, link: RNS.Link) -> None:
        """Callback cuando alguien se conecta hacia nosotros."""
        logger.info(f"Enlace RNS entrante establecido desde {link.get_remote_identity()}")
        link.set_packet_callback(self._on_rns_packet_from_link)
        link.set_link_closed_callback(self._on_link_closed)

    def _on_link_closed(self, link: RNS.Link) -> None:
        """Callback cuando un enlace se cierra."""
        logger.info("Enlace RNS cerrado.")
        # Si era nuestro enlace de salida, intentamos reconectar
        if self.config.rns_send_mode == "link" and link == self.rns_link:
            logger.info("El enlace de salida se cerró. Se intentará reabrir en el próximo envío.")
            self.rns_link = None

    def _on_rns_packet(self, data: bytes, packet: RNS.Packet) -> None:
        """Callback general para paquetes sueltos."""
        self._handle_incoming_data(data)
        
    def _on_rns_packet_from_link(self, message: bytes, packet: RNS.Packet) -> None:
        """Callback para paquetes que llegan por un enlace."""
        self._handle_incoming_data(message)

    def _handle_incoming_data(self, data: bytes) -> None:
        """Pasa los datos recibidos al callback de capa superior."""
        if self.on_message_callback:
            self.on_message_callback(data)

    def stop(self) -> None:
        """Detiene RNS."""
        logger.info("Deteniendo RNS Worker...")
        self._batching_active = False
        if self.rns_link and self.rns_link.status == RNS.Link.ACTIVE:
            self.rns_link.teardown()

    def send(self, data: bytes) -> None:
        """
        Envía datos por RNS. Si el batching está activo, lo encola.
        Si no, lo envía inmediatamente.
        """
        if not self.remote_destination:
            logger.debug("Mensaje a enviar descartado: No hay destino remoto configurado.")
            return

        if self.config.batching_enabled:
            self._batch_queue.put(data)
        else:
            self._do_send(data)

    def _do_send(self, data: bytes) -> None:
        """Ejecuta el envío real usando Packet o Link."""
        try:
            if self.config.rns_send_mode == "link":
                # Asegurar enlace
                if not self.rns_link or self.rns_link.status != RNS.Link.ACTIVE:
                    self._establish_link()
                    
                if self.rns_link and self.rns_link.status == RNS.Link.ACTIVE:
                    packet = RNS.Packet(self.rns_link, data)
                    packet.send()
                    logger.debug(f"Datos enviados vía RNS Link ({len(data)} bytes)")
                else:
                    logger.warning("No se pudo enviar por Link (no activo).")
                    
            else:
                # Modo Packet
                packet = RNS.Packet(self.remote_destination, data)
                packet.send()
                logger.debug(f"Datos enviados vía RNS Packet ({len(data)} bytes)")
                
        except ValueError as e:
             logger.error(f"Error de tamaño de paquete RNS: {e}. ¿Excede la MTU (~500 bytes)?")
        except Exception as e:
            logger.error(f"Error enviando por RNS: {e}")

    def _batch_worker(self) -> None:
        """Hilo para procesar los paquetes agrupados y enviarlos juntos si es posible."""
        while self._batching_active:
            batch: List[bytes] = []
            
            try:
                # Esperamos el primer paquete
                first_item = self._batch_queue.get(timeout=1.0)
                batch.append(first_item)
                
                # Tenemos el primero, esperamos la ventana de tiempo a ver si llegan más
                start_time = time.time()
                while time.time() - start_time < self.config.batching_window_seconds:
                    try:
                        # Polling rápido no bloqueante
                        item = self._batch_queue.get(block=False)
                        batch.append(item)
                        if len(batch) >= self.config.batching_max_buffered_packets:
                            break
                    except queue.Empty:
                        time.sleep(0.05)
                        
                # TODO: RNS no soporta empaquetar múltiples paquetes "lógicamente" en uno solo
                # de forma nativa sin que nosotros armemos un protocolo propio (ej: meterlos en una lista de msgpack).
                # Por simplicidad y evitar exceder la MTU estricta, los enviamos como ráfaga
                # lo cual igualmente reduce colisiones si se usa CSMA en el medio físico subyacente.
                for item in batch:
                    self._do_send(item)
                    
            except queue.Empty:
                pass
            except Exception as e:
                logger.error(f"Error en el thread de batching RNS: {e}")
