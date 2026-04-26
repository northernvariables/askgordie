"""Gordie's screen persona — a web-based animated face served via Flask+SocketIO.

Display modes:
  Single display: Switches between voice persona and prompt based on face presence.
  Dual display:   Primary display always shows voice persona.
                  Secondary display always shows prompt/text interface.
                  Both receive real-time state + response updates via SocketIO.

Also serves the opinion recorder: MJPEG camera preview + recording controls.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gordie_voice.app import GordieApp
    from gordie_voice.config import DisplayConfig
    from gordie_voice.device.registry import DeviceRegistry
    from gordie_voice.factcheck.checker import FactChecker
    from gordie_voice.opinions.uploader import OpinionUploader
    from gordie_voice.payments.manager import PaymentManager
    from gordie_voice.queue.manager import QueueManager
    from gordie_voice.recording.recorder import OpinionRecorder

log = structlog.get_logger()

def _get_lan_ip() -> str:
    """Get the device's LAN IP for QR codes that mobile phones need to reach."""
    import socket as _socket
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "gordie.local"  # Fallback to mDNS


TEMPLATE_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


class PersonaServer:
    """Flask+SocketIO server for the Gordie display persona."""

    def __init__(self, config: DisplayConfig) -> None:
        from flask import Flask
        from flask_socketio import SocketIO

        self.config = config
        self._app_ref: GordieApp | None = None
        self._recorder: OpinionRecorder | None = None
        self._uploader: OpinionUploader | None = None
        self._device_registry: DeviceRegistry | None = None
        self._payments: PaymentManager | None = None
        self._fact_checker: FactChecker | None = None
        self._queue: QueueManager | None = None
        self._persona_mgr = None  # PersonaManager
        self._stt: object | None = None  # STTProvider for transcribing recordings

        self.flask = Flask(
            __name__,
            template_folder=str(TEMPLATE_DIR),
            static_folder=str(STATIC_DIR),
        )
        # Register custom Jinja2 filter for parsing JSON strings in templates
        import json as _json
        self.flask.jinja_env.filters["fromjson"] = lambda s: _json.loads(s) if isinstance(s, str) else s
        self.socketio = SocketIO(self.flask, cors_allowed_origins="*", async_mode="threading")
        self._thread: threading.Thread | None = None
        self._countdown_thread: threading.Thread | None = None
        self._setup_routes()
        self._setup_socket_handlers()

    def set_app(self, app: GordieApp) -> None:
        self._app_ref = app

    def set_recorder(self, recorder: OpinionRecorder) -> None:
        self._recorder = recorder

    def set_uploader(self, uploader: OpinionUploader) -> None:
        self._uploader = uploader

    def set_device_registry(self, registry: DeviceRegistry) -> None:
        self._device_registry = registry

    def set_payments(self, payments: PaymentManager) -> None:
        self._payments = payments

    def set_persona_manager(self, mgr) -> None:
        self._persona_mgr = mgr

    def set_queue(self, queue: QueueManager) -> None:
        self._queue = queue

    def set_fact_checker(self, checker: FactChecker, stt: object) -> None:
        self._fact_checker = checker
        self._stt = stt

    def set_session_store(self, store) -> None:
        self._session_store = store

    def emit_session_qr(self, session_id: str) -> None:
        self.socketio.emit("session_ended", {"session_id": session_id})

    def _setup_routes(self) -> None:
        from flask import Response, render_template

        tpl_args = {"theme": self.config.theme, "touch": self.config.touch_enabled}

        @self.flask.route("/")
        def index():
            """Root: in dual mode, shows primary display's configured mode. Single mode: auto-switch."""
            if self.config.dual_display:
                return render_template("persona.html", **tpl_args, lock_mode=self.config.primary_mode)
            return render_template("persona.html", **tpl_args, lock_mode="")

        @self.flask.route("/primary")
        def primary_display():
            """Primary display — shows whatever mode is configured."""
            return render_template("persona.html", **tpl_args, lock_mode=self.config.primary_mode)

        @self.flask.route("/secondary")
        def secondary_display():
            """Secondary display — shows whatever mode is configured."""
            return render_template("persona.html", **tpl_args, lock_mode=self.config.secondary_mode)

        @self.flask.route("/voice")
        def voice_display():
            """Force voice persona view regardless of config."""
            return render_template("persona.html", **tpl_args, lock_mode="voice")

        @self.flask.route("/prompt")
        def prompt_display():
            """Force prompt/text view regardless of config."""
            return render_template("persona.html", **tpl_args, lock_mode="prompt")

        @self.flask.route("/queue/join")
        def queue_join_page():
            """Mobile-friendly page for scanning QR to join the queue."""
            return render_template("queue_join.html")

        @self.flask.route("/qr/queue")
        def qr_queue():
            """QR code linking to the queue join page."""
            import io
            import qrcode

            device_id = ""
            if self._device_registry:
                device_id = self._device_registry._device_id

            host = _get_lan_ip()
            port = self.config.port
            url = f"http://{host}:{port}/queue/join?device={device_id}"

            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#ff1e38", back_color="#0a0a0f")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return Response(buf.getvalue(), mimetype="image/png")

        @self.flask.route("/qr/register")
        def qr_register():
            """Generate a QR code PNG linking to CanadaGPT registration with device context."""
            import io
            import urllib.parse
            import qrcode

            params = {}
            if self._device_registry:
                params["device"] = self._device_registry._device_id
                if self._device_registry.riding_code:
                    params["riding"] = self._device_registry.riding_code
                if self._device_registry.riding_name:
                    params["riding_name"] = self._device_registry.riding_name

            base_url = self.config.registration_url or "https://canadagpt.ca/register"
            url = f"{base_url}?{urllib.parse.urlencode(params)}" if params else base_url

            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#ff1e38", back_color="#0a0a0f")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return Response(buf.getvalue(), mimetype="image/png")

        @self.flask.route("/camera/feed")
        def camera_feed():
            """MJPEG stream of the camera for opinion recording preview."""
            if not self._recorder:
                return "Camera not available", 503
            return Response(
                self._recorder.generate_mjpeg(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )

        @self.flask.route("/s/<session_id>")
        def session_recap(session_id):
            if not hasattr(self, '_session_store') or not self._session_store:
                return "Sessions not available", 503
            session = self._session_store.get_session(session_id)
            if not session:
                return render_template("session.html", deleted=True)
            messages = self._session_store.get_messages(session_id)
            self._session_store.mark_scanned(session_id)
            from datetime import datetime
            started = datetime.fromisoformat(session["started_at"])
            ended = datetime.fromisoformat(session["ended_at"]) if session["ended_at"] else datetime.utcnow()
            duration_min = max(1, round((ended - started).total_seconds() / 60))
            riding_name = None
            if self._device_registry and hasattr(self._device_registry, 'riding_name'):
                riding_name = self._device_registry.riding_name
            return render_template(
                "session.html",
                session=session,
                messages=messages,
                duration_min=duration_min,
                riding_name=riding_name,
            )

        @self.flask.route("/s/<session_id>/delete", methods=["POST"])
        def session_delete(session_id):
            if hasattr(self, '_session_store') and self._session_store:
                self._session_store.delete_session(session_id)
            return render_template("session.html", deleted=True)

        @self.flask.route("/qr/session/<session_id>")
        def qr_session(session_id):
            import io
            import qrcode
            host = _get_lan_ip()
            port = self.config.port
            url = f"http://{host}:{port}/s/{session_id}"
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#EC2024", back_color="#0a0a0f")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return Response(buf.getvalue(), mimetype="image/png")

    def _setup_socket_handlers(self) -> None:
        import random
        from gordie_voice.recording.categories import (
            CATEGORIES, CATEGORIES_BY_ID, CHALLENGES_BY_CATEGORY, CHALLENGE_QUESTIONS,
        )

        @self.socketio.on("connect")
        def on_connect():
            log.info("display_client_connected")
            if self._app_ref:
                self.socketio.emit("state", {
                    "state": self._app_ref.state.value,
                    "mode": self._app_ref.mode.value,
                    "dual_display": self.config.dual_display,
                })
            # Send persona info for portrait display
            if self._persona_mgr:
                self.socketio.emit("persona_info", self._persona_mgr.get_display_info())

            # Send payment config
            if self._payments and self._payments.config:
                pc = self._payments.config
                self.socketio.emit("payment_config", {
                    "recording_fee": {
                        "enabled": pc.recording_fee_enabled,
                        "amount_cents": pc.recording_fee_cents,
                        "currency": pc.recording_fee_currency,
                        "description": pc.recording_fee_description,
                    },
                    "donation": {
                        "enabled": pc.donation_enabled,
                        "presets_cents": pc.donation_presets_cents,
                        "custom_allowed": pc.donation_custom,
                        "min_cents": pc.donation_min_cents,
                        "max_cents": pc.donation_max_cents,
                        "recipient": pc.donation_recipient,
                        "charity_number": pc.donation_charity_number,
                        "tax_receipt": pc.donation_tax_receipt,
                    },
                    "commerce": {
                        "enabled": pc.commerce_enabled,
                        "catalog": pc.commerce_catalog,
                    },
                    "ready": self._payments.is_ready,
                })

            # Send device info for QR display
            if self._device_registry:
                self.socketio.emit("device_info", {
                    "device_id": self._device_registry._device_id,
                    "riding_name": self._device_registry.riding_name,
                    "riding_code": self._device_registry.riding_code,
                    "activated": self._device_registry.is_activated,
                    "activation_code": self._device_registry.activation_code if not self._device_registry.is_activated else None,
                })
            # Send available opinion categories
            self.socketio.emit("opinion_categories", {
                "categories": [
                    {"id": c.id, "label": c.label, "prompt": c.prompt, "icon": c.icon}
                    for c in CATEGORIES
                ],
            })

        @self.socketio.on("tap_wake")
        def on_tap_wake(data=None):
            if self._app_ref:
                log.info("tap_wake_triggered")
                from gordie_voice.app import State
                if self._app_ref.state == State.IDLE:
                    self._app_ref._set_state(State.LISTENING)

        @self.socketio.on("prompt_submit")
        def on_prompt(data):
            text = data.get("text", "").strip()
            if text and self._app_ref:
                log.info("prompt_received", text=text[:50])
                self._app_ref.handle_prompt_query(text)

        @self.socketio.on("register_phone")
        def on_register_phone(data):
            phone = data.get("phone", "")
            if phone and self._app_ref and self._app_ref.registration:
                success = self._app_ref.registration.send_otp(phone)
                self.socketio.emit("registration_status", {
                    "step": "otp_sent",
                    "success": success,
                })

        @self.socketio.on("verify_code")
        def on_verify_code(data):
            phone = data.get("phone", "")
            code = data.get("code", "")
            if phone and code and self._app_ref and self._app_ref.registration:
                success = self._app_ref.registration.verify_otp(phone, code)
                self.socketio.emit("registration_status", {
                    "step": "verified",
                    "success": success,
                })

        # ---- Opinion recording ----

        @self.socketio.on("opinion_start_preview")
        def on_start_preview(data=None):
            """Start camera preview before recording."""
            if not self._recorder:
                self.socketio.emit("opinion_error", {"message": "Camera not available"})
                return
            # Pause presence detection while recording
            if self._app_ref and self._app_ref.presence:
                self._app_ref.presence.stop()
            success = self._recorder.start_preview()
            self.socketio.emit("opinion_preview_status", {"active": success})

        @self.socketio.on("opinion_start_recording")
        def on_start_recording(data):
            """Begin 60-second opinion recording."""
            category_id = data.get("category", "freeform")
            if category_id not in CATEGORIES_BY_ID:
                category_id = "freeform"

            if not self._recorder:
                self.socketio.emit("opinion_error", {"message": "Recorder not available"})
                return

            # Set duration based on registration status
            is_registered = (
                self._app_ref
                and self._app_ref.registration
                and self._app_ref.registration.is_authenticated
            )
            self._recorder.set_duration_for_user(bool(is_registered))
            max_s = self._recorder._active_max_duration

            success = self._recorder.start_recording(category_id)
            if success:
                category = CATEGORIES_BY_ID[category_id]
                self.socketio.emit("opinion_recording_started", {
                    "category": category_id,
                    "prompt": category.prompt,
                    "max_seconds": max_s,
                })
                # Start countdown broadcast
                self._countdown_thread = threading.Thread(
                    target=self._broadcast_countdown, daemon=True
                )
                self._countdown_thread.start()
            else:
                self.socketio.emit("opinion_error", {"message": "Failed to start recording"})

        @self.socketio.on("opinion_stop_recording")
        def on_stop_recording(data=None):
            """Stop recording early (user pressed stop)."""
            if self._recorder and self._recorder.is_recording:
                elapsed = round(self._recorder._active_max_duration -self._recorder.remaining_seconds)
                category = self._recorder._category_id
                file_path = self._recorder.stop_recording()
                self._recorder.stop_preview()
                if self._app_ref and self._app_ref.presence:
                    self._app_ref.presence.start()

                # Trigger upload pipeline
                if file_path and self._uploader:
                    user_id = None
                    if self._app_ref and self._app_ref.registration and self._app_ref.registration.is_authenticated:
                        user_id = self._app_ref.registration.access_token  # Will be resolved to user_id
                    consent_text = "I consent to my recording being submitted to CanadaGPT for review and potential publication."
                    self._uploader.process_recording(
                        file_path=file_path,
                        category=category,
                        duration_s=elapsed,
                        user_id=user_id,
                        consent_text=consent_text,
                    )

                self.socketio.emit("opinion_recording_complete", {
                    "saved": file_path is not None,
                    "uploaded": file_path is not None and self._uploader is not None,
                    "duration_s": elapsed,
                    "fact_check": self._fact_checker is not None,
                })

                # Kick off fact-check in background
                if file_path and self._fact_checker:
                    threading.Thread(
                        target=self._run_fact_check,
                        args=(file_path, category),
                        daemon=True,
                    ).start()

        @self.socketio.on("opinion_cancel")
        def on_cancel(data=None):
            """Cancel recording/preview without saving."""
            if self._recorder:
                if self._recorder.is_recording:
                    self._recorder.stop_recording()
                self._recorder.stop_preview()
            if self._app_ref and self._app_ref.presence:
                self._app_ref.presence.start()
            self.socketio.emit("opinion_cancelled", {})

        # ---- Payments ----

        @self.socketio.on("payment_recording_fee")
        def on_recording_fee(data=None):
            """Charge the recording fee before allowing opinion recording."""
            if not self._payments or not self._payments.is_ready:
                self.socketio.emit("payment_result", {"success": False, "reason": "Payments not configured"})
                return

            def on_complete(success, payment_data):
                self.socketio.emit("payment_result", {
                    "success": success,
                    "type": "recording_fee",
                    **payment_data,
                })

            checkout_id = self._payments.charge_recording_fee(callback=on_complete)
            if checkout_id:
                self.socketio.emit("payment_pending", {
                    "type": "recording_fee",
                    "checkout_id": checkout_id,
                    "message": "Tap or insert your card on the reader",
                })
            else:
                self.socketio.emit("payment_result", {"success": False, "reason": "Failed to create checkout"})

        @self.socketio.on("payment_donation")
        def on_donation(data):
            """Process a donation payment."""
            amount_cents = data.get("amount_cents", 0)
            donor_email = data.get("email")
            if not self._payments or not self._payments.is_ready:
                self.socketio.emit("payment_result", {"success": False, "reason": "Payments not configured"})
                return

            # Validate against configured min/max
            pc = self._payments.config
            if amount_cents < pc.donation_min_cents or amount_cents > pc.donation_max_cents:
                self.socketio.emit("payment_result", {
                    "success": False,
                    "reason": f"Amount must be between ${pc.donation_min_cents/100:.2f} and ${pc.donation_max_cents/100:.2f}",
                })
                return

            def on_complete(success, payment_data):
                self.socketio.emit("payment_result", {
                    "success": success,
                    "type": "donation",
                    "amount_cents": amount_cents,
                    **payment_data,
                })

            checkout_id = self._payments.charge_donation(
                amount_cents=amount_cents,
                donor_email=donor_email,
                callback=on_complete,
            )
            if checkout_id:
                self.socketio.emit("payment_pending", {
                    "type": "donation",
                    "checkout_id": checkout_id,
                    "amount_cents": amount_cents,
                    "message": "Tap or insert your card on the reader",
                })

        @self.socketio.on("payment_commerce")
        def on_commerce(data):
            """Process a commerce purchase."""
            item_ids = data.get("items", [])  # [{"id": "sticker-01", "quantity": 1}]
            if not item_ids or not self._payments or not self._payments.is_ready:
                self.socketio.emit("payment_result", {"success": False, "reason": "Not available"})
                return

            # Resolve items from catalog
            catalog = {i["id"]: i for i in (self._payments.config.commerce_catalog or [])}
            items = []
            for req in item_ids:
                cat_item = catalog.get(req["id"])
                if cat_item:
                    items.append({
                        "name": cat_item["name"],
                        "quantity": str(req.get("quantity", 1)),
                        "base_price_cents": cat_item["price_cents"],
                    })

            if not items:
                self.socketio.emit("payment_result", {"success": False, "reason": "No valid items"})
                return

            def on_complete(success, payment_data):
                self.socketio.emit("payment_result", {
                    "success": success,
                    "type": "commerce",
                    **payment_data,
                })

            checkout_id = self._payments.charge_commerce(items=items, callback=on_complete)
            if checkout_id:
                total = sum(i["base_price_cents"] * int(i["quantity"]) for i in items)
                self.socketio.emit("payment_pending", {
                    "type": "commerce",
                    "checkout_id": checkout_id,
                    "amount_cents": total,
                    "message": "Tap or insert your card on the reader",
                })

        @self.socketio.on("payment_cancel")
        def on_payment_cancel(data=None):
            if self._payments:
                self._payments.cancel_active_checkout()
                self.socketio.emit("payment_cancelled", {})

        # ---- Queue ----

        @self.socketio.on("queue_join")
        def on_queue_join(data):
            """Add user to the queue (after registration)."""
            if not self._queue:
                return
            result = self._queue.add_to_queue(
                display_name=data.get("display_name", ""),
                postal_code=data.get("postal_code", ""),
                phone=data.get("phone", ""),
                user_id=data.get("user_id"),
            )
            self.socketio.emit("queue_joined", result)
            # Broadcast queue update to all displays
            self._broadcast_queue_status()

        @self.socketio.on("queue_next")
        def on_queue_next(data=None):
            """Admin/auto: call the next person."""
            if not self._queue:
                return
            entry = self._queue.call_next()
            self._broadcast_queue_status()
            if entry:
                # Announce via TTS
                if self._app_ref:
                    try:
                        msg = f"Now serving number {entry.ticket_number}."
                        if entry.display_name:
                            msg += f" {entry.display_name}, please step up."
                        audio = self._app_ref.tts.synthesize(msg)
                        self._app_ref.playback.play(audio)
                    except Exception:
                        log.warning("queue_announce_tts_failed")

        @self.socketio.on("queue_skip")
        def on_queue_skip(data=None):
            if self._queue:
                self._queue.skip_current()
                self._broadcast_queue_status()

        # ---- Gordie Challenge ----

        @self.socketio.on("challenge_start")
        def on_challenge_start(data):
            """Pick a random challenge question for the selected category."""
            category_id = data.get("category", "")
            pool = CHALLENGES_BY_CATEGORY.get(category_id, CHALLENGE_QUESTIONS)
            question = random.choice(pool)
            self.socketio.emit("challenge_question", {
                "category": question.category_id,
                "question": question.question,
                "spoken_question": question.spoken_question,
            })
            # Speak the question via TTS if in voice mode
            if self._app_ref and self._app_ref.mode.value == "voice":
                try:
                    audio = self._app_ref.tts.synthesize(question.spoken_question)
                    self._app_ref.playback.play(audio)
                except Exception:
                    log.warning("challenge_tts_failed")

    def _run_fact_check(self, file_path: str, category: str) -> None:
        """Transcribe the recording and fact-check it, streaming results to the display."""
        if not self._fact_checker or not self._stt:
            return

        import subprocess
        import tempfile
        from pathlib import Path

        self.socketio.emit("fact_check_status", {"step": "transcribing"})

        try:
            # Extract audio from the video
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            subprocess.run(
                ["ffmpeg", "-y", "-i", file_path, "-ar", "16000", "-ac", "1", "-f", "wav", tmp_path],
                capture_output=True, timeout=60,
            )

            import wave as _wave
            with _wave.open(tmp_path, "rb") as wf:
                raw_audio = wf.readframes(wf.getnframes())
            transcript = self._stt.transcribe(raw_audio)
            Path(tmp_path).unlink(missing_ok=True)

            if not transcript or not transcript.strip():
                self.socketio.emit("fact_check_status", {"step": "no_claims", "transcript": ""})
                return

            self.socketio.emit("fact_check_status", {
                "step": "transcript_ready",
                "transcript": transcript,
            })

            # Run fact-check
            self.socketio.emit("fact_check_status", {"step": "checking"})
            result = self._fact_checker.check(transcript, category)

            # Stream individual claim results as they become available
            # (they're already computed, but we emit them one-by-one for the UI reveal effect)
            for i, claim in enumerate(result.claims):
                self.socketio.emit("fact_check_claim", {
                    "index": i,
                    "total": result.claim_count,
                    "claim": claim.claim,
                    "verdict": claim.verdict,
                    "confidence": claim.confidence,
                    "explanation": claim.explanation,
                    "correction": claim.correction,
                    "sources": claim.sources,
                })
                self.socketio.sleep(0.5)  # Brief pause between claims for visual effect

            # Final verdict
            self.socketio.emit("fact_check_complete", {
                "summary": result.summary,
                "accuracy_score": round(result.accuracy_score, 2),
                "accuracy_pct": round(result.accuracy_score * 100),
                "claim_count": result.claim_count,
                "checked_at": result.checked_at,
                "verdict_label": result.verdict_label,
                "verdict_emoji": result.verdict_emoji,
            })
            log.info("fact_check_delivered", claims=result.claim_count, accuracy=round(result.accuracy_score, 2))

        except Exception:
            log.exception("fact_check_failed")
            self.socketio.emit("fact_check_status", {"step": "error", "message": "Fact-check unavailable"})

    def _broadcast_countdown(self) -> None:
        """Send countdown ticks to all clients while recording."""
        while self._recorder and self._recorder.is_recording:
            remaining = self._recorder.remaining_seconds
            self.socketio.emit("opinion_countdown", {
                "remaining_s": round(remaining),
                "elapsed_s": round(self._recorder._active_max_duration -remaining),
            })
            if remaining <= 0:
                # Auto-complete
                category = self._recorder._category_id
                file_path = self._recorder.stop_recording()
                self._recorder.stop_preview()
                if self._app_ref and self._app_ref.presence:
                    self._app_ref.presence.start()

                if file_path and self._uploader:
                    consent_text = "I consent to my recording being submitted to CanadaGPT for review and potential publication."
                    self._uploader.process_recording(
                        file_path=file_path,
                        category=category,
                        duration_s=60,
                        consent_text=consent_text,
                    )

                self.socketio.emit("opinion_recording_complete", {
                    "saved": file_path is not None,
                    "uploaded": file_path is not None and self._uploader is not None,
                    "duration_s": self._recorder._active_max_duration,
                    "fact_check": self._fact_checker is not None,
                })

                if file_path and self._fact_checker:
                    threading.Thread(
                        target=self._run_fact_check,
                        args=(file_path, category),
                        daemon=True,
                    ).start()
                break
            self.socketio.sleep(1)

    def _broadcast_queue_status(self) -> None:
        """Send queue status to all connected clients."""
        if self._queue:
            status = self._queue.get_queue_status()
            waiting = self._queue.get_waiting_list()
            self.socketio.emit("queue_update", {**status, "waiting_list": waiting})

    def broadcast_state(self, state: str, mode: str) -> None:
        self.socketio.emit("state", {
            "state": state,
            "mode": mode,
            "dual_display": self.config.dual_display,
        })

    def broadcast_response_chunk(self, chunk: str) -> None:
        self.socketio.emit("response_chunk", {"text": chunk})

    def broadcast_response_done(self) -> None:
        self.socketio.emit("response_done", {})

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.socketio.run,
            args=(self.flask,),
            kwargs={"host": self.config.host, "port": self.config.port, "allow_unsafe_werkzeug": True},
            daemon=True,
        )
        self._thread.start()
        log.info(
            "persona_server_started",
            port=self.config.port,
            dual_display=self.config.dual_display,
        )

    def stop(self) -> None:
        if self._recorder:
            self._recorder.stop_preview()
        log.info("persona_server_stopped")
