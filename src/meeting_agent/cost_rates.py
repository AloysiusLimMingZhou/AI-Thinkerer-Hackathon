"""Versioned USD usage estimates; all persisted amounts are integer microdollars."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

PRICE_VERSION = "2026-10-15"


class UnknownRate(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CostQuote:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    audio_seconds: float = 0
    characters: int = 0


def dollars_to_micro(value) -> int:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Cost limits must be finite and nonnegative")
    return int((amount * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def estimate_micro_usd(quote: CostQuote) -> int:
    for name in ("input_tokens", "output_tokens", "characters"):
        value = getattr(quote, name)
        if type(value) is not int or value < 0:
            raise ValueError("Usage counts must be nonnegative integers")
    seconds = Decimal(str(quote.audio_seconds))
    if not seconds.is_finite() or seconds < 0:
        raise ValueError("Audio duration must be finite and nonnegative")
    if quote.model == "gpt-transcribe":
        if quote.input_tokens or quote.output_tokens or quote.characters:
            raise ValueError("Unexpected transcription usage")
        amount = seconds.to_integral_value(rounding=ROUND_CEILING) * 75
    elif quote.model == "eleven_v4_turbo":
        if quote.input_tokens or quote.output_tokens or seconds:
            raise ValueError("Unexpected speech usage")
        amount = Decimal(quote.characters * 40)
    elif quote.model == "gpt-6-luna":
        if seconds or quote.characters or quote.input_tokens > 272_000:
            raise ValueError("Unsupported Luna context or usage")
        amount = Decimal(quote.input_tokens) / 10 + Decimal(quote.output_tokens) / 2
    else:
        raise UnknownRate("No approved price for configured model")
    return int(amount.to_integral_value(rounding=ROUND_CEILING))
