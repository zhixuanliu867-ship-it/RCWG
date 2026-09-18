"""Single-machine reservation ledger, not a provider billing cap or distributed quota."""
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .common import now_utc

MAX_RESERVED_MICRO_USD = 1_000_000
MAX_PROBES = 5

def reserve(ledger: Path, usd: str) -> str:
    try:
        amount = Decimal(usd)
        if not amount.is_finite() or amount <= 0 or amount > Decimal("0.20"):
            raise ValueError("Reserve must be finite and in (0, 0.20] USD")
        micro = int((amount * 1_000_000).to_integral_value(rounding="ROUND_CEILING"))
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid reserve") from exc
    ledger.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ledger, timeout=5, isolation_level=None)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, created TEXT, micro_usd INTEGER, status TEXT)")
        con.execute("BEGIN IMMEDIATE")
        count, total = con.execute("SELECT COUNT(*), COALESCE(SUM(micro_usd), 0) FROM reservations").fetchone()
        if count >= MAX_PROBES or total + micro > MAX_RESERVED_MICRO_USD:
            raise ValueError("LOCAL_RESERVATION_GATE: review the ledger and provider billing before further probes")
        rid = uuid.uuid4().hex
        con.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (rid, now_utc(), micro, "RESERVED"))
        con.execute("COMMIT")
        return rid
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()

def finish(ledger: Path, rid: str, status: str) -> None:
    # Reservations remain charged to the LOCAL gate on errors/timeouts and success.
    with sqlite3.connect(ledger) as con:
        con.execute("UPDATE reservations SET status=? WHERE id=?", (status, rid))
