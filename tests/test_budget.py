from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from meeting_agent.budget import BudgetService, BudgetExceeded, DuplicateOperation, PaidCallContext
from meeting_agent.config import Settings
from meeting_agent.cost_rates import CostQuote, UnknownRate, estimate_micro_usd
from meeting_agent.repository import SQLiteRepository


def make_budget(tmp_path, **kwargs):
    settings = Settings(database_path=tmp_path / "budget.db", **kwargs)
    return BudgetService(SQLiteRepository(settings.database_path), settings)


def context(key):
    return PaidCallContext(None, key, "test")


def test_published_rates_and_rounding():
    assert estimate_micro_usd(CostQuote("gpt-transcribe", audio_seconds=60)) == 4500
    assert estimate_micro_usd(CostQuote("gpt-transcribe", audio_seconds=0.1)) == 75
    assert estimate_micro_usd(CostQuote("eleven_v4_turbo", characters=1000)) == 40000
    assert estimate_micro_usd(CostQuote("gpt-6-luna", input_tokens=100000, output_tokens=1000)) == 10500


@pytest.mark.parametrize("quote", [
    CostQuote("unknown"), CostQuote("gpt-transcribe", audio_seconds=float("nan")),
    CostQuote("gpt-transcribe", audio_seconds=-1), CostQuote("gpt-6-luna", input_tokens=272001),
    CostQuote("gpt-6-luna", output_tokens=-1),
])
def test_invalid_or_unknown_quotes_fail_closed(quote):
    with pytest.raises((ValueError, UnknownRate)):
        estimate_micro_usd(quote)


def test_reservation_settlement_duplicate_and_restart(tmp_path):
    budget = make_budget(tmp_path)
    reservation = budget.reserve(context("one"), CostQuote("eleven_v4_turbo", characters=1000))
    assert reservation.reserved_micro_usd == 44000
    with pytest.raises(DuplicateOperation):
        budget.reserve(context("one"), CostQuote("eleven_v4_turbo", characters=1))
    budget.mark_dispatched(reservation.id)
    budget.settle(reservation.id, CostQuote("eleven_v4_turbo", characters=1000), "provider-1")
    budget.settle(reservation.id, CostQuote("eleven_v4_turbo", characters=1000), "provider-1")
    restored = make_budget(tmp_path)
    assert restored.status().settled_micro_usd == 40000
    assert restored.status().held_micro_usd == 0


def test_uncertain_holds_survive_time_and_cannot_release(tmp_path):
    budget = make_budget(tmp_path)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    budget.clock = lambda: now
    r = budget.reserve(context("timeout"), CostQuote("eleven_v4_turbo", characters=5000))
    budget.mark_dispatched(r.id)
    budget.mark_uncertain(r.id)
    now += timedelta(days=8)
    budget.release_unsent(r.id)
    assert budget.status().held_micro_usd == 220000
    assert budget.status().uncertain_count == 1


def test_concurrent_admission_never_exceeds_hard_cap(tmp_path):
    budget = make_budget(tmp_path, ai_monthly_soft_limit_usd="0.04", ai_monthly_hard_limit_usd="0.05")
    def admit(key):
        try:
            budget.reserve(context(key), CostQuote("eleven_v4_turbo", characters=1000))
            return "admitted"
        except BudgetExceeded:
            return "denied"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, ["a", "b"]))
    assert results.count("admitted") == 1
    status = budget.status()
    assert status.settled_micro_usd + status.held_micro_usd <= 50000
    assert status.soft_warning
    assert status.warning_count == 1


def test_local_midnight_settlement_stays_in_original_month(tmp_path):
    budget = make_budget(tmp_path)
    now = datetime(2026, 10, 31, 15, 59, 59, tzinfo=UTC)
    budget.clock = lambda: now
    r = budget.reserve(context("cross-midnight"), CostQuote("eleven_v4_turbo", characters=1000))
    assert r.month == "2026-10"
    budget.mark_dispatched(r.id)
    now += timedelta(seconds=1)
    assert budget.status().month == "2026-11"
    assert budget.status().held_micro_usd == 0
    budget.settle(r.id, CostQuote("eleven_v4_turbo", characters=1000))
    assert budget.status().settled_micro_usd == 0
    with budget.repository._connect() as db:
        assert db.execute("SELECT month, settled_micro_usd FROM ai_cost_ledger").fetchone()[:] == ("2026-10", 40000)


def test_budget_endpoint_auth_and_defaults(tmp_path):
    from fastapi.testclient import TestClient
    from meeting_agent.api import create_app
    from test_api import FakeBrain, FakeVoice
    app = create_app(settings=Settings(database_path=tmp_path/"api.db", backend_api_token="test"), brain=FakeBrain(), voice=FakeVoice())
    client = TestClient(app)
    assert client.get("/budget/status").status_code == 401
    status = client.get("/budget/status", headers={"Authorization": "Bearer test"}).json()
    assert status["soft_limit_micro_usd"] == 5_000_000
    assert status["hard_limit_micro_usd"] == 8_000_000
    assert status["timezone"] == "Asia/Kuala_Lumpur"


@pytest.mark.parametrize("kwargs", [
    {"ai_monthly_soft_limit_usd": "9"}, {"ai_monthly_hard_limit_usd": "-1"},
    {"ai_monthly_soft_limit_usd": "NaN"}, {"ai_budget_timezone": "not-a-timezone"},
])
def test_invalid_budget_settings_fail_closed(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
