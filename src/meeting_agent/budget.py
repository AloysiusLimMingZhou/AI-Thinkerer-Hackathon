"""One durable operator budget for every paid AI operation in the application."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_CEILING
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .cost_rates import CostQuote, PRICE_VERSION, dollars_to_micro, estimate_micro_usd


class DuplicateOperation(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    def __init__(self, status):
        super().__init__("Monthly AI budget cannot cover this request.")
        self.status = status


@dataclass(frozen=True, slots=True)
class PaidCallContext:
    session_id: str | None
    operation_id: str
    purpose: str


_context: ContextVar[PaidCallContext | None] = ContextVar("paid_call", default=None)


@contextmanager
def paid_call_context(context: PaidCallContext):
    token = _context.set(context)
    try:
        yield context
    finally:
        _context.reset(token)


def current_paid_call(purpose: str) -> PaidCallContext:
    context = _context.get()
    return PaidCallContext(
        context.session_id if context else None,
        f"{context.operation_id}:{purpose}" if context else str(uuid4()),
        purpose,
    )


@dataclass(frozen=True, slots=True)
class Reservation:
    id: str
    month: str
    reserved_micro_usd: int


class BudgetStatus(BaseModel):
    month: str
    timezone: str
    reset_at: datetime
    soft_limit_micro_usd: int
    hard_limit_micro_usd: int
    settled_micro_usd: int
    held_micro_usd: int
    available_micro_usd: int
    uncertain_count: int
    soft_warning: bool
    warning_count: int
    last_denied: bool
    providers: dict[str, dict[str, int]]
    price_version: str = PRICE_VERSION
    scope: str = "This application's OpenAI and ElevenLabs usage estimates; excludes Recall, hosting, subscriptions, taxes and other applications."


class BudgetService:
    def __init__(self, repository, settings, *, clock=None):
        self.repository, self.settings = repository, settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.zone = ZoneInfo(settings.ai_budget_timezone)
        self.soft = dollars_to_micro(settings.ai_monthly_soft_limit_usd)
        self.hard = dollars_to_micro(settings.ai_monthly_hard_limit_usd)
        with repository._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ai_cost_ledger(
                    id TEXT PRIMARY KEY, session_id TEXT, purpose TEXT NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, price_version TEXT NOT NULL,
                    month TEXT NOT NULL, reserved_micro_usd INTEGER NOT NULL,
                    settled_micro_usd INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL,
                    usage_json TEXT, provider_request_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS ai_cost_month ON ai_cost_ledger(month,state);
                CREATE TABLE IF NOT EXISTS ai_budget_month(
                    month TEXT PRIMARY KEY, warned INTEGER NOT NULL DEFAULT 0,
                    last_denied INTEGER NOT NULL DEFAULT 0);
            """)
            # A previous process may have submitted even a reservation not yet marked sent.
            db.execute("UPDATE ai_cost_ledger SET state='uncertain' WHERE state IN ('reserved','dispatched')")

    def _period(self):
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("Budget clock must be timezone-aware")
        local = now.astimezone(self.zone)
        reset = datetime(local.year + (local.month == 12), local.month % 12 + 1, 1, tzinfo=self.zone)
        return local.strftime("%Y-%m"), reset, now.astimezone(UTC).isoformat()

    @staticmethod
    def _totals(db, month):
        row = db.execute("""
            SELECT COALESCE(SUM(CASE WHEN state='settled' THEN settled_micro_usd ELSE 0 END),0),
                   COALESCE(SUM(CASE WHEN state IN ('reserved','dispatched','uncertain') THEN reserved_micro_usd ELSE 0 END),0)
            FROM ai_cost_ledger WHERE month=?
        """, (month,)).fetchone()
        return int(row[0]), int(row[1])

    def reserve(self, context: PaidCallContext, quote: CostQuote) -> Reservation:
        cost = estimate_micro_usd(quote)
        maximum = int((Decimal(cost) * Decimal("1.10")).to_integral_value(rounding=ROUND_CEILING))
        month, _, now = self._period()
        denied = False
        with self.repository._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM ai_cost_ledger WHERE id=?", (context.operation_id,)).fetchone():
                raise DuplicateOperation("Paid operation already recorded; do not automatically dispatch it again")
            spent, held = self._totals(db, month)
            db.execute("INSERT OR IGNORE INTO ai_budget_month(month) VALUES(?)", (month,))
            if spent + held + maximum > self.hard:
                db.execute("UPDATE ai_budget_month SET last_denied=1 WHERE month=?", (month,))
                denied = True
            else:
                provider = "elevenlabs" if quote.model.startswith("eleven_") else "openai"
                db.execute("""INSERT INTO ai_cost_ledger
                    (id,session_id,purpose,provider,model,price_version,month,reserved_micro_usd,state,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,'reserved',?,?)""",
                    (context.operation_id,context.session_id,context.purpose,provider,quote.model,PRICE_VERSION,month,maximum,now,now))
                if spent + held + maximum >= self.soft:
                    db.execute("UPDATE ai_budget_month SET warned=1 WHERE month=?", (month,))
        if denied:
            raise BudgetExceeded(self.status())
        return Reservation(context.operation_id, month, maximum)

    def mark_dispatched(self, id: str) -> None:
        with self.repository._connect() as db:
            db.execute("UPDATE ai_cost_ledger SET state='dispatched',updated_at=? WHERE id=? AND state='reserved'", (self._period()[2],id))

    def mark_uncertain(self, id: str) -> None:
        with self.repository._connect() as db:
            db.execute("UPDATE ai_cost_ledger SET state='uncertain',updated_at=? WHERE id=? AND state IN ('reserved','dispatched')", (self._period()[2],id))

    def release_unsent(self, id: str) -> None:
        with self.repository._connect() as db:
            db.execute("UPDATE ai_cost_ledger SET state='released',updated_at=? WHERE id=? AND state='reserved'", (self._period()[2],id))

    def settle(self, id: str, usage: CostQuote, provider_request_id: str | None = None) -> None:
        import json
        from dataclasses import asdict
        cost = estimate_micro_usd(usage)
        with self.repository._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM ai_cost_ledger WHERE id=?", (id,)).fetchone()
            if not row or row["model"] != usage.model:
                raise ValueError("Reservation/model mismatch")
            if row["state"] == "settled":
                return
            if row["state"] == "released":
                raise ValueError("Cannot settle an unsent operation")
            db.execute("""UPDATE ai_cost_ledger SET state='settled',settled_micro_usd=?,usage_json=?,
                provider_request_id=?,updated_at=? WHERE id=?""",
                (cost,json.dumps(asdict(usage)),provider_request_id,self._period()[2],id))
            spent, held = self._totals(db, row["month"])
            if spent + held >= self.soft:
                db.execute("UPDATE ai_budget_month SET warned=1 WHERE month=?", (row["month"],))

    def ensure_available(self, quotes) -> None:
        maximum = sum(int((Decimal(estimate_micro_usd(q))*Decimal("1.10")).to_integral_value(rounding=ROUND_CEILING)) for q in quotes)
        status = self.status()
        if maximum > status.available_micro_usd:
            raise BudgetExceeded(status)

    def status(self) -> BudgetStatus:
        month, reset, _ = self._period()
        with self.repository._connect() as db:
            spent, held = self._totals(db, month)
            warning = db.execute("SELECT * FROM ai_budget_month WHERE month=?", (month,)).fetchone()
            uncertain = db.execute("SELECT COUNT(*) FROM ai_cost_ledger WHERE month=? AND state='uncertain'", (month,)).fetchone()[0]
            rows = db.execute("""SELECT provider,
                SUM(CASE WHEN state='settled' THEN settled_micro_usd ELSE 0 END) AS spent,
                SUM(CASE WHEN state IN ('reserved','dispatched','uncertain') THEN reserved_micro_usd ELSE 0 END) AS held
                FROM ai_cost_ledger WHERE month=? GROUP BY provider""", (month,)).fetchall()
        return BudgetStatus(month=month, timezone=self.settings.ai_budget_timezone, reset_at=reset,
            soft_limit_micro_usd=self.soft,hard_limit_micro_usd=self.hard,settled_micro_usd=spent,
            held_micro_usd=held,available_micro_usd=max(0,self.hard-spent-held),uncertain_count=uncertain,
            soft_warning=bool(warning and warning["warned"]),warning_count=int(bool(warning and warning["warned"])),
            last_denied=bool(warning and warning["last_denied"]),
            providers={r["provider"]:{"settled_micro_usd":r["spent"],"held_micro_usd":r["held"]} for r in rows})
