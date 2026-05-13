"""Export Postgres run history to an Excel workbook with one sheet per source.

``run_logs`` does not store ``mode``; we infer bucket from ``run_id``:

  * **Intraday** — ``run_id`` starts with ``intraday-`` or ``retrigger-`` (scheduler / WS retrigger)
  * **Short_term** — ``run_id`` starts with ``short_term-`` (daily scheduler)
  * **Long_term** — ``run_id`` starts with ``long_term-`` (daily scheduler)
  * **Analyzer** — everything else, including **manual intraday** from
    ``POST /api/analyze`` (16-char hex ``run_id``\ s). Scheduler intraday uses
    ``intraday-`` / ``retrigger-`` prefixes and appears in the Intraday block.

The **Intraday** sheet also includes a second block: the ``intraday_signals`` table
(actionable BUY/SELL intraday rows only). The run_logs block above it lists every
intraday scheduler completion (including HOLD) for the 5-minute history.

Usage (from repo root)::

    uv run python scripts/export_runs_to_excel.py
    uv run python scripts/export_runs_to_excel.py --out exports/my_runs.xlsx --limit 2000

``--limit`` applies **per** run_logs query and to intraday_signals (default 10000).

``--tz`` (default ``Asia/Kolkata``): timestamps from Postgres are usually UTC-aware;
they are converted to this zone then written as naive Excel datetimes so the
clock matches local market time (not raw UTC).

Requires ``DATABASE_URL`` and dev deps ``openpyxl`` + ``tzdata`` (``uv sync``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path


def _load_dotenv_from_repo_root() -> None:
    """Populate os.environ from ``<repo>/.env`` when keys are unset (no python-dotenv)."""
    root = Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        os.environ[key] = val


def _dsn_for_asyncpg(database_url: str) -> str:
    u = database_url.strip()
    if u.startswith("postgres://"):
        u = u.replace("postgres://", "postgresql://", 1)
    u = u.replace("postgresql+asyncpg://", "postgresql://", 1)
    return u


_RUN_LOGS_SELECT = """
    SELECT run_id, ticker, market, status, final_signal, overrides_active,
           requires_human_review, llm_tokens_in, llm_tokens_out,
           llm_cost_usd, latency_ms, started_at, completed_at, error
    FROM run_logs
"""


def _datetimes_for_excel(df, tz: str) -> None:  # type: ignore[no-untyped-def]
    """Excel has no timezone; show wall clock in ``tz`` (e.g. IST), not UTC.

    Handles: pandas ``datetimetz``, naive ``datetime64`` (treated as UTC), and
    ``object`` columns of Python ``datetime`` (asyncpg sometimes yields these).
    """
    import pandas as pd  # noqa: PLC0415

    def _to_wall_clock(series):  # type: ignore[no-untyped-def]
        if isinstance(series.dtype, pd.DatetimeTZDtype):
            out = series.dt.tz_convert(tz)
        else:
            # Naive timestamps from Postgres are UTC wall clock in this app.
            out = pd.to_datetime(series, utc=True).dt.tz_convert(tz)
        return out.dt.tz_localize(None)

    for col in list(df.columns):
        s = df[col]
        if s.empty or not s.notna().any():
            continue
        try:
            if pd.api.types.is_datetime64_any_dtype(s):
                try:
                    df[col] = _to_wall_clock(s)
                except Exception:
                    df[col] = (
                        pd.to_datetime(s, utc=True).dt.tz_convert("UTC").dt.tz_localize(None)
                    )
                continue
            if s.dtype == object:
                sample = s.dropna().iloc[0]
                if isinstance(sample, datetime):
                    try:
                        df[col] = _to_wall_clock(pd.to_datetime(s, utc=True))
                    except Exception:
                        df[col] = (
                            pd.to_datetime(s, utc=True)
                            .dt.tz_convert("UTC")
                            .dt.tz_localize(None)
                        )
        except Exception:
            continue


async def _export(out_path: Path, limit: int, tz: str) -> None:
    try:
        import asyncpg  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise SystemExit("asyncpg is required (project dependency).") from e

    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise SystemExit("pandas is required (project dependency).") from e

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Set it in .env or the environment, "
            "then run from the repo root: uv run python scripts/export_runs_to_excel.py"
        )

    dsn = _dsn_for_asyncpg(url)
    conn = await asyncpg.connect(dsn)
    try:
        intraday_runs = await conn.fetch(
            f"{_RUN_LOGS_SELECT} WHERE run_id LIKE 'intraday-%' OR run_id LIKE 'retrigger-%' "
            f"ORDER BY started_at DESC LIMIT $1",
            limit,
        )
        short_term = await conn.fetch(
            f"{_RUN_LOGS_SELECT} WHERE run_id LIKE 'short_term-%' "
            f"ORDER BY started_at DESC LIMIT $1",
            limit,
        )
        long_term = await conn.fetch(
            f"{_RUN_LOGS_SELECT} WHERE run_id LIKE 'long_term-%' "
            f"ORDER BY started_at DESC LIMIT $1",
            limit,
        )
        analyzer = await conn.fetch(
            f"{_RUN_LOGS_SELECT} WHERE run_id NOT LIKE 'intraday-%' "
            f"AND run_id NOT LIKE 'retrigger-%' AND run_id NOT LIKE 'short_term-%' "
            f"AND run_id NOT LIKE 'long_term-%' ORDER BY started_at DESC LIMIT $1",
            limit,
        )
        intraday_signals = await conn.fetch(
            """
            SELECT id, run_id, ticker, signal, composite_score, confidence,
                   entry_price, stop_loss, target_price, data_coverage_pct,
                   mode, primary_interval, timestamp
            FROM intraday_signals
            ORDER BY timestamp DESC
            LIMIT $1
            """,
            limit,
        )
    finally:
        await conn.close()

    df_id_runs = pd.DataFrame([dict(r) for r in intraday_runs])
    df_st = pd.DataFrame([dict(r) for r in short_term])
    df_lt = pd.DataFrame([dict(r) for r in long_term])
    df_an = pd.DataFrame([dict(r) for r in analyzer])
    df_sig = pd.DataFrame([dict(r) for r in intraday_signals])

    for frame in (df_id_runs, df_st, df_lt, df_an, df_sig):
        if not frame.empty:
            _datetimes_for_excel(frame, tz)

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            # Intraday: run_logs (intraday/retrigger) + spacer + intraday_signals table
            row = 0
            df_id_runs.to_excel(writer, sheet_name="Intraday", index=False, startrow=row)
            row += len(df_id_runs) + 1  # + header row from pandas
            row += 1  # blank spacer
            pd.DataFrame([["intraday_signals (DB table)"]]).to_excel(
                writer, sheet_name="Intraday", index=False, header=False, startrow=row
            )
            row += 1
            df_sig.to_excel(writer, sheet_name="Intraday", index=False, startrow=row)

            df_st.to_excel(writer, sheet_name="Short_term", index=False)
            df_lt.to_excel(writer, sheet_name="Long_term", index=False)
            df_an.to_excel(writer, sheet_name="Analyzer", index=False)
    except ImportError as e:
        raise SystemExit(
            "openpyxl is required for .xlsx. Install dev deps: uv sync"
        ) from e
    except PermissionError as e:
        raise SystemExit(
            f"Permission denied writing {out_path}.\n"
            "  On Windows this usually means the file is open in Excel (or locked by "
            "OneDrive). Close the workbook and any preview pane, then run again.\n"
            "  Or write to a new file:\n"
            "    uv run python scripts/export_runs_to_excel.py --out exports/runs_export_new.xlsx"
        ) from e

    print(
        f"Wrote {out_path}\n"
        f"  Times in sheet: {tz} (local wall clock for Excel)\n"
        f"  Intraday runs: {len(df_id_runs)} (scheduler-style run_id only); "
        f"intraday_signals: {len(df_sig)} rows; "
        f"manual intraday run_logs are under Analyzer if present.\n"
        f"  Short_term: {len(df_st)}, Long_term: {len(df_lt)}, Analyzer: {len(df_an)}"
    )


def main() -> None:
    _load_dotenv_from_repo_root()
    p = argparse.ArgumentParser(
        description="Export run_logs (by run_id pattern) + intraday_signals to Excel."
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("exports") / "runs_export.xlsx",
        help="Output .xlsx path (default: exports/runs_export.xlsx)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=10_000,
        help="Max rows per SQL slice (default: 10000)",
    )
    p.add_argument(
        "--tz",
        type=str,
        default="Asia/Kolkata",
        help=(
            "IANA timezone for datetime columns in Excel (default: Asia/Kolkata). "
            "Use UTC for raw database UTC wall clock."
        ),
    )
    args = p.parse_args()
    asyncio.run(_export(args.out, args.limit, args.tz))


if __name__ == "__main__":
    main()
