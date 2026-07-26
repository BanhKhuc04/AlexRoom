import os
import pytest


def test_requirements_brain_no_mqtt_packages():
    """
    Regression test: Verify requirements-brain.txt exists and strictly contains NO MQTT dependencies.
    ALEX Brain PC is compute-only (STT/LLM/TTS) and must never possess MQTT capabilities.
    """
    req_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements-brain.txt")
    assert os.path.exists(req_file), "requirements-brain.txt must exist in repo root"

    with open(req_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    mqtt_forbidden = {"paho-mqtt", "mosquitto", "gmqtt", "mqtt", "aiomqtt"}

    for line in lines:
        stripped = line.strip().lower()
        if not stripped or stripped.startswith("#"):
            continue

        package_name = stripped.split("=")[0].split(">")[0].split("<")[0].split("~")[0].strip()
        assert package_name not in mqtt_forbidden, (
            f"Brain dependency file {req_file} must not contain MQTT package '{package_name}'"
        )
