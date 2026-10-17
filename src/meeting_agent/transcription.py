"""Bounded completed-utterance transcription; no raw-audio retention."""
import asyncio
import io
import wave
from typing import Protocol

from openai import AsyncOpenAI

from .budget import PaidCallContext, BudgetExceeded, DuplicateOperation
from .cost_rates import CostQuote
from .provider_calls import IntegrationUnavailable, paid_request


class Transcriber(Protocol):
    async def transcribe(self, wav: bytes, *, session_id: str, event_id: str) -> str: ...


def audio_duration(wav: bytes) -> float:
    if not isinstance(wav, bytes) or len(wav) > 512 * 1024:
        raise ValueError("Audio clip exceeds 512 KiB")
    try:
        with wave.open(io.BytesIO(wav), "rb") as file:
            if file.getnchannels() != 1 or file.getsampwidth() != 2 or file.getframerate() != 16000 or file.getcomptype() != "NONE":
                raise ValueError("Expected mono 16 kHz 16-bit PCM WAV")
            frames = file.getnframes()
            if not 0 < frames <= 15 * 16000:
                raise ValueError("Audio clip must be between zero and 15 seconds")
            if len(file.readframes(frames)) != frames * 2:
                raise ValueError("Truncated audio clip")
            return frames / 16000
    except (wave.Error, EOFError) as exc:
        raise ValueError("Invalid WAV audio") from exc


class OpenAITranscriber:
    def __init__(self, settings, budget, *, client=None):
        self.settings, self.budget, self._client = settings, budget, client

    async def transcribe(self, wav: bytes, *, session_id: str, event_id: str) -> str:
        seconds = audio_duration(wav)
        if not self.settings.openai_api_key:
            raise IntegrationUnavailable("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self.settings.openai_api_key, timeout=20, max_retries=0)
        quote = CostQuote(self.settings.openai_transcription_model, audio_seconds=seconds)
        context = PaidCallContext(session_id, f"stt:{session_id}:{event_id}", "transcription")
        try:
            async with paid_request(self.budget, context, quote) as reservation:
                async with asyncio.timeout(20):
                    result = await self._client.audio.transcriptions.create(
                        model=quote.model, file=("utterance.wav", wav, "audio/wav"))
                self.budget.settle(reservation.id, quote, getattr(result, "_request_id", None))
                text = getattr(result, "text", "")
                if not isinstance(text, str) or not text.strip() or len(text) > 10000:
                    raise IntegrationUnavailable("OpenAI transcription returned empty or oversized text")
                return text.strip()
        except (BudgetExceeded, DuplicateOperation, asyncio.CancelledError):
            raise
        except Exception:
            raise IntegrationUnavailable("OpenAI transcription failed; check configuration and connectivity") from None
