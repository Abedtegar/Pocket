"""Klien MQTT (paho-mqtt v2) untuk topik kacamata (plan.md 4.2)."""
from __future__ import annotations

import json
import logging
import time

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

SUB_TOPICS = [("glasses/hr", 0), ("glasses/status", 0), ("glasses/online", 1), ("glasses/camera/state", 1)]


def _parse(payload: bytes):
    text = payload.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except ValueError:
        return text


class MqttLink:
    def __init__(self, cfg, state, bus):
        self.cfg = cfg
        self.state = state
        self.bus = bus
        m = cfg.section("mqtt")
        self.host, self.port = m.get("host", "127.0.0.1"), int(m.get("port", 1883))
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=m.get("client_id", "guardian-sbc"), clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)

    def start(self) -> None:
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()

    # ---- publish ----
    def publish_json(self, topic: str, payload: dict, qos: int = 1, retain: bool = False) -> bool:
        info = self.client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def set_camera(self, params: dict) -> bool:
        return self.publish_json("glasses/camera/set", params, qos=1)

    def send_cmd(self, cmd: dict) -> bool:
        return self.publish_json("glasses/cmd", cmd, qos=1)

    # ---- callback (thread paho) ----
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            log.warning("MQTT gagal connect: %s", reason_code)
            return
        log.info("MQTT terhubung ke %s:%s", self.host, self.port)
        self.state.update("mqtt", connected=True)
        client.subscribe(SUB_TOPICS)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        log.warning("MQTT terputus: %s", reason_code)
        self.state.update("mqtt", connected=False)

    def _on_message(self, client, userdata, msg):
        data = _parse(msg.payload)
        now = time.time()
        topic = msg.topic
        if topic == "glasses/hr" and isinstance(data, dict):
            bpm = int(data.get("bpm", 0) or 0)
            finger = bool(data.get("finger", False))
            self.state.update("hr", bpm=bpm, finger=finger, ir=data.get("ir"), ts=now)
            self.state.update("glasses", last_hr=now)
            self.bus.publish_threadsafe("hr", {"bpm": bpm, "finger": finger, "ts": now})
        elif topic == "glasses/status" and isinstance(data, dict):
            self.state.update("glasses", last_status=now, batt_mv=data.get("batt_mv"), rssi=data.get("rssi"),
                              uptime=data.get("uptime"), heap=data.get("heap"), cam_ok=data.get("cam_ok"))
            self.bus.publish_threadsafe("glasses_status", data)
        elif topic == "glasses/online":
            online = str(data).strip('"') == "1"
            self.state.update("glasses", lwt_online=online)
            if online:
                self.state.update("glasses", last_status=now)
            log.info("glasses/online = %s", "1" if online else "0")
            self.bus.publish_threadsafe("glasses_online", online)
        elif topic == "glasses/camera/state":
            self.state.update("camera", esp_state=data)
            self.bus.publish_threadsafe("camera_state", data)
