"""Upload recorded opinions to Supabase Storage + insert metadata row.

Pipeline after recording completes:
1. Transcribe the audio via STT
2. Upload MP4 to Supabase Storage (private 'opinions' bucket)
3. Generate a thumbnail from the first frame
4. Insert metadata row into opinions table
5. Delete local file after successful upload
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings
    from gordie_voice.stt.base import STTProvider

log = structlog.get_logger()


class OpinionUploader:
    """Handles the full upload pipeline for opinion recordings."""

    def __init__(self, settings: Settings, stt: STTProvider | None = None) -> None:
        self._supabase_url = settings.supabase_url
        self._supabase_key = settings.supabase_service_role_key
        self._device_id = settings.device_id
        self._stt = stt
        self._client = httpx.Client(
            headers={
                "apikey": self._supabase_key,
                "Authorization": f"Bearer {self._supabase_key}",
            },
            timeout=120.0,
        )
        log.info("opinion_uploader_ready")

    def process_recording(
        self,
        file_path: str,
        category: str,
        duration_s: int,
        user_id: str | None = None,
        consent_text: str = "",
    ) -> None:
        """Process and upload a recording in a background thread."""
        thread = threading.Thread(
            target=self._upload_pipeline,
            args=(file_path, category, duration_s, user_id, consent_text),
            daemon=True,
        )
        thread.start()

    def _upload_pipeline(
        self,
        file_path: str,
        category: str,
        duration_s: int,
        user_id: str | None,
        consent_text: str,
    ) -> None:
        path = Path(file_path)
        if not path.exists():
            log.error("upload_file_not_found", path=file_path)
            return

        opinion_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        storage_path = f"{timestamp}/{opinion_id}.mp4"
        thumbnail_path = f"{timestamp}/{opinion_id}_thumb.jpg"

        try:
            # 1. Transcribe
            transcript = self._transcribe(path)

            # 2. Generate thumbnail from first frame
            thumb_bytes = self._generate_thumbnail(path)

            # 3. Upload video to storage
            self._upload_to_storage(storage_path, path.read_bytes(), "video/mp4")
            log.info("video_uploaded", storage_path=storage_path)

            # 4. Upload thumbnail
            if thumb_bytes:
                self._upload_to_storage(thumbnail_path, thumb_bytes, "image/jpeg")

            # 5. Insert metadata row
            row = {
                "id": opinion_id,
                "device_id": self._device_id,
                "category": category,
                "duration_s": duration_s,
                "storage_path": storage_path,
                "thumbnail_path": thumbnail_path if thumb_bytes else None,
                "user_id": user_id,
                "transcript": transcript,
                "transcribed_at": datetime.now(timezone.utc).isoformat() if transcript else None,
                "status": "pending_review",
                "consent_given": True,
                "consent_text": consent_text,
            }
            self._insert_metadata(row)
            log.info("opinion_metadata_inserted", id=opinion_id, category=category)

            # 6. Delete local file
            path.unlink(missing_ok=True)
            log.info("local_file_cleaned", path=file_path)

        except Exception:
            log.exception("upload_pipeline_failed", path=file_path)

    def _transcribe(self, video_path: Path) -> str | None:
        """Extract audio from video and transcribe via STT."""
        if not self._stt:
            return None

        import subprocess
        import tempfile

        tmp_path = None
        try:
            # Extract audio with ffmpeg
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(video_path),
                    "-ar", "16000", "-ac", "1", "-f", "wav", tmp_path,
                ],
                capture_output=True,
                timeout=60,
            )

            import wave as _wave
            with _wave.open(tmp_path, "rb") as wf:
                raw_audio = wf.readframes(wf.getnframes())
            transcript = self._stt.transcribe(raw_audio)
            log.info("opinion_transcribed", length=len(transcript))
            return transcript

        except Exception:
            log.exception("transcription_failed")
            return None
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def _generate_thumbnail(self, video_path: Path) -> bytes | None:
        """Extract first frame as a JPEG thumbnail."""
        try:
            cap = cv2.VideoCapture(str(video_path))
            ret, frame = cap.read()
            cap.release()
            if not ret:
                return None
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return jpeg.tobytes()
        except Exception:
            log.exception("thumbnail_generation_failed")
            return None

    def _upload_to_storage(self, path: str, data: bytes, content_type: str) -> None:
        """Upload a file to the Supabase 'opinions' storage bucket."""
        url = f"{self._supabase_url}/storage/v1/object/opinions/{path}"
        response = self._client.post(
            url,
            content=data,
            headers={"Content-Type": content_type},
        )
        response.raise_for_status()

    def _insert_metadata(self, row: dict) -> None:
        """Insert an opinion metadata row into the opinions table."""
        url = f"{self._supabase_url}/rest/v1/opinions"
        response = self._client.post(
            url,
            json=row,
            headers={"Content-Type": "application/json", "Prefer": "return=minimal"},
        )
        response.raise_for_status()
