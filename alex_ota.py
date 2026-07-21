import json
import logging
import uuid
from pathlib import Path
from typing import Any, Callable

from alex_store import AlexStore, utc_now

logger = logging.getLogger(__name__)

class AlexOtaService:
    def __init__(self, store: AlexStore, publisher: Callable, firmware_dir: Path, base_url: str):
        self.store = store
        self.publisher = publisher
        self.firmware_dir = firmware_dir
        self.base_url = base_url.rstrip("/")

    def get_manifest(self, node_id: str) -> dict[str, Any]:
        manifest_path = self.firmware_dir / node_id / "manifest.json"
        if not manifest_path.exists():
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read OTA manifest for {node_id}: {e}")
            return {}

    def get_ota_info(self, node_id: str, installed_version: str) -> dict[str, Any]:
        manifest = self.get_manifest(node_id)
        releases = manifest.get("releases", {})
        
        def semver_key(v: str) -> list[int]:
            try:
                return [int(x) for x in v.split(".")]
            except ValueError:
                return [0, 0, 0]
            
        available_versions = sorted(releases.keys(), key=semver_key, reverse=True)
        latest_version = available_versions[0] if available_versions else None
        
        update_available = False
        if latest_version and installed_version:
            update_available = semver_key(latest_version) > semver_key(installed_version)

        state_record = self.store.get_record("ota", node_id)
        if state_record:
            # Remove the implicit id injected by get_record
            state_record.pop("id", None)
            
        return {
            "installed_version": installed_version,
            "available_version": latest_version,
            "update_available": update_available,
            "releases": releases,
            "state": state_record
        }

    def request_ota(self, node_id: str, target_version: str, installed_version: str) -> dict[str, Any]:
        if not installed_version:
            raise ValueError("Không thể xác định phiên bản hiện tại của thiết bị")
            
        def semver_key(v: str) -> list[int]:
            try:
                return [int(x) for x in v.split(".")]
            except ValueError:
                return [0, 0, 0]
            
        if semver_key(target_version) <= semver_key(installed_version):
            raise ValueError(f"Phiên bản yêu cầu ({target_version}) phải lớn hơn phiên bản hiện tại ({installed_version})")

        manifest = self.get_manifest(node_id)
        release = manifest.get("releases", {}).get(target_version)
        if not release:
            raise ValueError(f"Không tìm thấy firmware release: {target_version}")

        operation_id = str(uuid.uuid4())
        download_token = str(uuid.uuid4())
        
        # Save short-lived token
        self.store.put_record("ota_tokens", download_token, {
            "node_id": node_id,
            "version": target_version,
            "created_at": utc_now()
        })

        # Track state machine
        state = {
            "operationId": operation_id,
            "targetVersion": target_version,
            "status": "requested",
            "requestedAt": utc_now()
        }
        self.store.put_record("ota", node_id, state)

        # Publish MQTT command
        topic = f"alex/v1/nodes/{node_id}/ota/command"
        download_url = f"{self.base_url}/api/v1/ota/firmware/{node_id}/{target_version}?token={download_token}"
        
        payload = {
            "commandId": operation_id,
            "targetVersion": target_version,
            "url": download_url,
            "sha256": release.get("sha256"),
            "size": release.get("size")
        }
        
        self.publisher(topic, payload, 1, False)
        return state

    def handle_ota_status(self, node_id: str, payload: dict[str, Any]) -> None:
        state = self.store.get_record("ota", node_id)
        if not state:
            return
            
        command_id = payload.get("commandId")
        if command_id != state.get("operationId"):
            return
            
        status = payload.get("status")
        if status:
            state["status"] = status
            state["statusUpdatedAt"] = utc_now()
            if "reason" in payload:
                state["reason"] = payload["reason"]
            self.store.put_record("ota", node_id, state)

    def evaluate_ota_completion(self, device: dict[str, Any]) -> None:
        node_id = device.get("node_id")
        installed_version = device.get("firmware")
        
        if not node_id or not installed_version:
            return
            
        state = self.store.get_record("ota", node_id)
        if not state:
            return
            
        status = state.get("status")
        if status in {"confirmed", "failed", "timeout"}:
            return
            
        # Target version matched => OTA success
        if device.get("connection") == "online" and state.get("targetVersion") == installed_version:
            state["status"] = "confirmed"
            state["confirmedAt"] = utc_now()
            self.store.put_record("ota", node_id, state)

    def validate_download_token(self, node_id: str, version: str, token: str) -> bool:
        record = self.store.get_record("ota_tokens", token)
        if not record:
            return False
        if record.get("node_id") != node_id or record.get("version") != version:
            return False
        return True
