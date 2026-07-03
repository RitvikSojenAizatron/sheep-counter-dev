import asyncio
import base64
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.app.services.databaseIO import mongo_client
from src.app.services.ws_manager import ws_manager
from src.app.store.state import (
    get_esp_control_state as build_esp_control_state,
)
from src.app.store.state import (
    get_esp_state as build_esp_state,
)
from src.app.store.state import (
    now_iso,
    state,
    state_lock,
)
from src.common.BaseMosquittoMqttClient import BaseMosquittoMqttClient
from src.common.Loggers import get_api_logger
from src.common.MQTTTopics import MQTTTopics

mqtt_loop: asyncio.AbstractEventLoop | None = None
control_mqtt_client: BaseMosquittoMqttClient | None = None
LOGGER = get_api_logger()

DETECTION_BUFFER_TTL_S = 8
PIPELINE_HEARTBEAT_TIMEOUT_S = 60
RING_BUFFER_CAP = 10000

detection_buffer: dict[str, dict] = {}  # object_uuid -> {payload, expires_at}
detection_buffer_lock = threading.Lock()

# Pipeline heartbeat watchdog — tracks the last time we received a heartbeat.
# Initialized to current time so the watchdog doesn't fire before the pipeline
# has had a chance to start up and send its first heartbeat.
_last_pipeline_heartbeat: float = time.monotonic()
_heartbeat_lock = threading.Lock()

# Hostname agent request/reply correlation
_pending_hostname_requests: dict[str, asyncio.Future] = {}
_pending_hostname_lock = threading.Lock()


# --- HELPERS ---#
def _camera_id_from_source_name(source_name: str) -> str | None:
    with state_lock:
        for cam in state["cameras"]:
            if cam["name"] == source_name:
                return cam["id"]
    return None


def _check_camera_id(id: str) -> bool:
    with state_lock:
        for cam in state["cameras"]:
            if cam["id"] == id:
                return True
    return False


# --- PIPELINE CALLBACKS ---#
def pipeline_heartbeat_callback(client, userdata, message):
    raw = json.loads(message.payload.decode())
    fps = float(raw.get("pipeline_fps", 0.0))
    latency = float(raw.get("pipeline_latency", 0))

    with _heartbeat_lock:
        global _last_pipeline_heartbeat
        _last_pipeline_heartbeat = time.monotonic()

    with state_lock:
        payload = {
            "heartbeat": now_iso(),
            "fps": fps,
            "latencyMs": latency,
            "mqttConnected": True,
            "espConnected": False,
        }
    if mqtt_loop:
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast_pipeline_metric(payload), mqtt_loop
        )


def pipeline_log_callback(client, userdata, message):
    raw = json.loads(message.payload.decode())
    with state_lock:
        state["serviceLogs"].append(raw)


def live_count_callback(client, userdata, message):
    raw = json.loads(message.payload.decode())
    source_id = raw.get("source_id")
    if source_id is None:
        return
    if not _check_camera_id(str(source_id)):
        return
    payload = {
        "cameraId": str(source_id),
        "sheepCount": raw.get("sheep_count", 0),
        "online": True,
        "lastUpdate": now_iso(),
    }
    if mqtt_loop:
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast_camera_metric(payload), mqtt_loop
        )


def source_connect_callback(client, userdata, message):
    raw = json.loads(message.payload.decode())
    source_name = raw.get("name")
    camera_id = _camera_id_from_source_name(source_name)
    if camera_id and mqtt_loop:
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast_source_status({"cameraId": camera_id, "online": True}),
            mqtt_loop,
        )


def source_disconnect_callback(client, userdata, message):
    raw = json.loads(message.payload.decode())
    print("source disconnect callback")
    source_name = raw.get("name")
    camera_id = _camera_id_from_source_name(source_name)
    if camera_id and mqtt_loop:
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast_source_status(
                {"cameraId": camera_id, "online": False}
            ),
            mqtt_loop,
        )


def bridge_heartbeat_callback(client, userdata, message):
    raw = json.loads(message.payload.decode())
    with state_lock:
        payload = {"heartbeat": now_iso()}
    if mqtt_loop:
        asyncio.run_coroutine_threadsafe(
            ws_manager.broadcast_bridge_state(payload), mqtt_loop
        )


def bridge_log_callback(client, userdata, message):
    raw = json.loads(message.payload.decode())
    with state_lock:
        state["serviceLogs"].append(raw)


def _resolve_hostname_future(request_id: str | None, payload: dict) -> None:
    if not request_id:
        return
    with _pending_hostname_lock:
        fut = _pending_hostname_requests.pop(request_id, None)
    if fut is None or fut.done():
        return
    loop = fut.get_loop()
    loop.call_soon_threadsafe(fut.set_result, payload)


def hostname_state_callback(client, userdata, message):
    try:
        raw = json.loads(message.payload.decode())
    except Exception as e:
        LOGGER.error("hostname_state_callback decode error: %s", e)
        return
    with state_lock:
        current = state.setdefault("deviceHostname", {})
        current["observed"] = raw.get("avahiAdvertisedName") or raw.get("osHostname")
        current["osHostname"] = raw.get("osHostname")
        current["avahiConfiguredName"] = raw.get("avahiConfiguredName")
        current["avahiAdvertisedName"] = raw.get("avahiAdvertisedName")
        current["conflictDetected"] = bool(raw.get("conflictDetected", False))
        current["mongoConnected"] = bool(raw.get("mongoConnected", False))
        current["lastUpdated"] = raw.get("lastUpdated")
        current["agentVersion"] = raw.get("agentVersion")


def hostname_set_result_callback(client, userdata, message):
    try:
        raw = json.loads(message.payload.decode())
    except Exception as e:
        LOGGER.error("hostname_set_result_callback decode error: %s", e)
        return
    _resolve_hostname_future(raw.get("requestId"), raw)


def hostname_check_result_callback(client, userdata, message):
    try:
        raw = json.loads(message.payload.decode())
    except Exception as e:
        LOGGER.error("hostname_check_result_callback decode error: %s", e)
        return
    _resolve_hostname_future(raw.get("requestId"), raw)


async def await_hostname_response(request_id: str, timeout: float) -> dict:
    """Register a future for the given request_id and wait for a matching reply."""
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    with _pending_hostname_lock:
        _pending_hostname_requests[request_id] = fut
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        with _pending_hostname_lock:
            _pending_hostname_requests.pop(request_id, None)
        raise


def publish_hostname_reload(request_id: str) -> None:
    if control_mqtt_client is None:
        LOGGER.warning("Hostname reload publish skipped; MQTT client not ready")
        return
    control_mqtt_client.publish(
        MQTTTopics.HOSTNAME_RELOAD, {"requestId": request_id}, qos=1
    )


def publish_hostname_check(request_id: str, name: str) -> None:
    if control_mqtt_client is None:
        LOGGER.warning("Hostname check publish skipped; MQTT client not ready")
        return
    control_mqtt_client.publish(
        MQTTTopics.HOSTNAME_CHECK, {"requestId": request_id, "name": name}, qos=1
    )


# --- TTL SWEEPER ---#


def _ttl_sweeper():
    while True:
        time.sleep(2)
        now = time.time()
        expired = []
        with detection_buffer_lock:
            for obj_uuid, entry in list(detection_buffer.items()):
                if now >= entry["expires_at"]:
                    expired.append(entry["payload"])
                    del detection_buffer[obj_uuid]
        for detection in expired:
            try:
                _create_and_persist_event(detection, None)
            except Exception as e:
                LOGGER.error("TTL sweeper error: %s", e)


# --- PIPELINE HEARTBEAT WATCHDOG ---#


def _pipeline_heartbeat_watchdog():
    """
    Background thread that restarts the vision-pipeline container if no
    heartbeat has been received within PIPELINE_HEARTBEAT_TIMEOUT_S seconds.
    """
    global _last_pipeline_heartbeat
    from src.app.services.docker_service import restart_service

    # Give the pipeline time to start up before we begin monitoring.
    time.sleep(PIPELINE_HEARTBEAT_TIMEOUT_S)

    while True:
        time.sleep(10)  # check every 10 seconds
        with _heartbeat_lock:
            elapsed = time.monotonic() - _last_pipeline_heartbeat

        if elapsed > PIPELINE_HEARTBEAT_TIMEOUT_S:
            LOGGER.warning(
                "Pipeline heartbeat watchdog: no heartbeat for %.0fs "
                "(timeout=%ds) — restarting vision-pipeline container",
                elapsed,
                PIPELINE_HEARTBEAT_TIMEOUT_S,
            )
            try:
                restart_service("vision-pipeline")
                LOGGER.info("Pipeline heartbeat watchdog: restart issued")
            except Exception as e:
                LOGGER.error("Pipeline heartbeat watchdog: restart failed: %s", e)

            # Reset the timer so we don't spam restarts — give the container
            # a full timeout window to come back up and send a heartbeat.
            with _heartbeat_lock:
                _last_pipeline_heartbeat = time.monotonic()


# --- SUBSCRIPTIONS ---#


def _subscribe_topics(mqtt_client):
    mqtt_client.subscribe(
        topic=MQTTTopics.PIPELINE_HEARTBEAT,
        qos=0,
        callback=pipeline_heartbeat_callback,
    )
    mqtt_client.subscribe(
        topic=MQTTTopics.BRIDGE_HEARTBEAT,
        qos=0,
        callback=bridge_heartbeat_callback,
    )


    mqtt_client.subscribe(
        topic=MQTTTopics.PIPELINE_LOGS, qos=0, callback=pipeline_log_callback
    )
    mqtt_client.subscribe(
        topic=MQTTTopics.BRIDGE_LOGS_TOCLOUD, qos=0, callback=bridge_log_callback
    )
    mqtt_client.subscribe(topic=MQTTTopics.ESP_LOGS, qos=0, callback=esp_log_callback)

    mqtt_client.subscribe(
        topic=MQTTTopics.SOURCE_CONNECT, qos=0, callback=source_connect_callback
    )

    mqtt_client.subscribe(
        topic=MQTTTopics.SOURCE_DISCONNECT, qos=0, callback=source_disconnect_callback
    )

    mqtt_client.subscribe(
        topic=MQTTTopics.SOURCES_STATUS, qos=0, callback=source_status_callback
    )
    mqtt_client.subscribe(
        topic=MQTTTopics.PIPELINE_LIVE_COUNT, qos=0, callback=live_count_callback
    )
   
    mqtt_client.subscribe(
        topic=MQTTTopics.ESP_STATE_UPDATE,
        qos=0,
        callback=esp_state_update_callback,
    )

    mqtt_client.subscribe(
        topic=MQTTTopics.HOSTNAME_STATE,
        qos=1,
        callback=hostname_state_callback,
    )
    mqtt_client.subscribe(
        topic=MQTTTopics.HOSTNAME_SET_RESULT,
        qos=1,
        callback=hostname_set_result_callback,
    )
    mqtt_client.subscribe(
        topic=MQTTTopics.HOSTNAME_CHECK_RESULT,
        qos=1,
        callback=hostname_check_result_callback,
    )


dashboard_mqtt_client: BaseMosquittoMqttClient | None = None


def start_mqtt(loop):
    global mqtt_loop, LOGGER, dashboard_mqtt_client, control_mqtt_client
    mqtt_loop = loop

    mqtt_client = BaseMosquittoMqttClient(
        client_id="state-change-listener", logger=LOGGER
    )
    mqtt_client.configure_health(
        service_name="vision-dashboard",
        heartbeat_interval_s=10,
        extra_status={"svc": "vision-dashboard"},
    )
    mqtt_client.connect()
    _subscribe_topics(mqtt_client)
    dashboard_mqtt_client = mqtt_client
    control_mqtt_client = mqtt_client

    sweeper = threading.Thread(target=_ttl_sweeper, daemon=True)
    sweeper.start()


def publish_esp_control(payload: dict) -> None:
    if control_mqtt_client is None:
        LOGGER.warning("ESP control publish skipped because MQTT client is not ready.")
        return
    control_mqtt_client.publish(MQTTTopics.ESP_CONTROL, payload, qos=1)


watchdog = threading.Thread(target=_pipeline_heartbeat_watchdog, daemon=True)
watchdog.start()
LOGGER.info(
    "Pipeline heartbeat watchdog started (timeout=%ds)",
    PIPELINE_HEARTBEAT_TIMEOUT_S,
)
