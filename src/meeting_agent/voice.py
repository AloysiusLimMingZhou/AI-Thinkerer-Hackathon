"""ElevenLabs v4 Turbo Text to Dialogue synthesis with bounded paid requests."""
import asyncio
import base64
import binascii
import json
from urllib.parse import urlencode

from websockets.asyncio.client import connect as websocket_connect

from .budget import BudgetExceeded, DuplicateOperation, current_paid_call
from .cost_rates import CostQuote
from .provider_calls import IntegrationUnavailable, paid_request

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_FRAME_BYTES = 1024 * 1024


class ElevenLabsVoice:
    def __init__(self, settings, budget=None, *, connect=None):
        self.settings, self.budget = settings, budget
        self.connect = connect or websocket_connect

    async def generate(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip() or len(text) > 5000:
            raise ValueError("Speech text must contain 1-5000 characters")
        if not self.settings.elevenlabs_api_key:
            raise IntegrationUnavailable("ELEVENLABS_API_KEY is not configured")
        quote = CostQuote(self.settings.elevenlabs_model_id, characters=len(text))
        uri = "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input?" + urlencode({
            "model_id": quote.model, "output_format": "mp3_44100_128"})
        try:
            async with paid_request(self.budget, current_paid_call("speech"), quote) as reservation:
                async with asyncio.timeout(30):
                    async with self.connect(uri,
                        additional_headers={"xi-api-key":self.settings.elevenlabs_api_key},
                        open_timeout=10, close_timeout=2, max_size=MAX_FRAME_BYTES) as socket:
                        await socket.send(json.dumps({"voices":[self.settings.elevenlabs_voice_id]}))
                        await socket.send(json.dumps({"inputs":[{
                            "text":text,"voice_id":self.settings.elevenlabs_voice_id,"new_turn":True}]}))
                        await socket.send(json.dumps({"close_socket":True}))
                        audio = bytearray()
                        while True:
                            raw = await socket.recv()
                            if not isinstance(raw, (str, bytes)) or len(raw) > MAX_FRAME_BYTES:
                                raise ValueError("Oversized speech frame")
                            message = json.loads(raw)
                            if not isinstance(message, dict) or message.get("error"):
                                raise ValueError("Speech provider error")
                            encoded = message.get("audio")
                            if encoded:
                                if not isinstance(encoded, str):
                                    raise ValueError("Invalid audio encoding")
                                chunk = base64.b64decode(encoded, validate=True)
                                if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                                    raise ValueError("Speech output exceeds 8 MiB")
                                audio.extend(chunk)
                            if message.get("is_final") is True:
                                if not audio:
                                    raise ValueError("Empty speech audio")
                                self.budget.settle(reservation.id, quote)
                                return bytes(audio)
        except (BudgetExceeded, DuplicateOperation, asyncio.CancelledError):
            raise
        except Exception:
            raise IntegrationUnavailable("ElevenLabs speech failed; check v4 Turbo access, voice and connectivity") from None
