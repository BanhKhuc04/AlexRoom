import json
import unittest
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from app import store, ALEX_OTA_TOKEN_TTL_SECONDS, get_firmware, ALEX_FIRMWARE_DIR
from alex_store import utc_now
from fastapi import HTTPException

class TestOtaToken(unittest.TestCase):
    def setUp(self):
        self.store = store
        with self.store._lock, self.store.session() as db:
            db.execute("DELETE FROM domain_records WHERE domain='ota_tokens'")
            db.execute("DELETE FROM domain_records WHERE domain='ota'")
            
        self.node_id = "esp01"
        self.version = "1.0.1"
        self.firmware_dir = ALEX_FIRMWARE_DIR / self.node_id / self.version
        self.firmware_dir.mkdir(parents=True, exist_ok=True)
        self.firmware_path = self.firmware_dir / "firmware.bin"
        
        self.mock_content = b"fake_firmware_bytes"
        with open(self.firmware_path, "wb") as f:
            f.write(self.mock_content)
            
        self.expected_sha256 = hashlib.sha256(self.mock_content).hexdigest()
        
    def tearDown(self):
        if self.firmware_path.exists():
            self.firmware_path.unlink()
        if self.firmware_dir.exists():
            self.firmware_dir.rmdir()

    def _create_token(self, node_id, version, created_at_iso=None):
        token = str(uuid.uuid4())
        if created_at_iso is None:
            created_at_iso = utc_now()
        self.store.put_record("ota_tokens", token, {
            "node_id": node_id,
            "version": version,
            "created_at": created_at_iso
        })
        return token

    def test_1_valid_token_downloads_matching_firmware(self):
        token = self._create_token(self.node_id, self.version)
        response = get_firmware(self.node_id, self.version, token)
        self.assertEqual(Path(response.path), self.firmware_path)
        with open(response.path, "rb") as f:
            content = f.read()
        downloaded_sha256 = hashlib.sha256(content).hexdigest()
        self.assertEqual(downloaded_sha256, self.expected_sha256)

    def test_2_missing_token_is_rejected(self):
        # We don't have fastapi routing here, so missing token means passing None or empty string to get_firmware
        with self.assertRaises(HTTPException) as ctx:
            get_firmware(self.node_id, self.version, None)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_3_unknown_token_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            get_firmware(self.node_id, self.version, "wrong_token")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_4_token_for_wrong_node_is_rejected(self):
        token = self._create_token("wrong_node", self.version)
        with self.assertRaises(HTTPException) as ctx:
            get_firmware(self.node_id, self.version, token)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_5_token_for_wrong_version_is_rejected(self):
        token = self._create_token(self.node_id, "9.9.9")
        with self.assertRaises(HTTPException) as ctx:
            get_firmware(self.node_id, self.version, token)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_6_expired_token_is_rejected(self):
        expired_time = datetime.now(timezone.utc) - timedelta(seconds=ALEX_OTA_TOKEN_TTL_SECONDS + 10)
        token = self._create_token(self.node_id, self.version, expired_time.isoformat())
        with self.assertRaises(HTTPException) as ctx:
            get_firmware(self.node_id, self.version, token)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_7_malformed_created_at_is_rejected(self):
        token = self._create_token(self.node_id, self.version, "not-a-date")
        with self.assertRaises(HTTPException) as ctx:
            get_firmware(self.node_id, self.version, token)
        self.assertEqual(ctx.exception.status_code, 403)
        
    def test_8_token_inside_ttl_remains_valid(self):
        # Almost expired, but still valid
        valid_time = datetime.now(timezone.utc) - timedelta(seconds=ALEX_OTA_TOKEN_TTL_SECONDS - 10)
        token = self._create_token(self.node_id, self.version, valid_time.isoformat())
        response = get_firmware(self.node_id, self.version, token)
        self.assertEqual(Path(response.path), self.firmware_path)

if __name__ == "__main__":
    unittest.main()
