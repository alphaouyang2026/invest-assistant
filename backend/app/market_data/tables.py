"""The four tables, as SQLAlchemy Core sees them.

Private to the market data module (spec §2): nothing outside
`app.market_data` imports this. The column types turn the TEXT the
migration declares back into `Decimal` and `date` on the way out.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Column, Integer, MetaData, Table, Text, TypeDecorator


class DecimalText(TypeDecorator):
    """A `Decimal` stored as its exact text, so no float ever touches it."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


class IsoDate(TypeDecorator):
    """A `date` stored as `YYYY-MM-DD`, which sorts the way dates do."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: date | None, dialect) -> str | None:
        return None if value is None else value.isoformat()

    def process_result_value(self, value: str | None, dialect) -> date | None:
        return None if value is None else date.fromisoformat(value)


metadata = MetaData()

instruments = Table(
    "instruments", metadata,
    Column("code", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("name_en", Text, nullable=False),
    Column("scale_category", Text, nullable=False),
    Column("first_listed_seen", IsoDate),
    Column("last_listed_seen", IsoDate),
)

segment_periods = Table(
    "segment_periods", metadata,
    Column("code", Text, primary_key=True),
    Column("valid_from", IsoDate, primary_key=True),
    Column("valid_to", IsoDate),
    Column("market_code", Text, nullable=False),
    Column("product_category", Text, nullable=False),
    Column("sector33", Text, nullable=False),
)

daily_bars = Table(
    "daily_bars", metadata,
    Column("code", Text, primary_key=True),
    Column("date", IsoDate, primary_key=True),
    Column("open", DecimalText),
    Column("high", DecimalText),
    Column("low", DecimalText),
    Column("close", DecimalText),
    Column("volume", DecimalText),
    Column("turnover", DecimalText),
    Column("adjustment_factor", DecimalText, nullable=False),
    Column("ex_rights_type", Integer),
    Column("upper_limit_hit", Boolean, nullable=False),
    Column("lower_limit_hit", Boolean, nullable=False),
    Column("quality_status", Text, nullable=False),
)

trading_calendar = Table(
    "trading_calendar", metadata,
    Column("date", IsoDate, primary_key=True),
    Column("holiday_division", Integer, nullable=False),
)
