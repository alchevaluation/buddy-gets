from __future__ import annotations

from decimal import Decimal
from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass


class Budget(Base):
    __tablename__ = 'budgets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    presentation_currency: Mapped[str] = mapped_column(String(3), default='BRL')


class Period(Base):
    __tablename__ = 'periods'
    __table_args__ = (UniqueConstraint('budget_id', 'position'), CheckConstraint('ends_on >= starts_on'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey('budgets.id', ondelete='CASCADE'))
    name: Mapped[str] = mapped_column(String(100))
    starts_on: Mapped[str] = mapped_column(String(10))
    ends_on: Mapped[str] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer)


class Line(Base):
    __tablename__ = 'lines'
    __table_args__ = (UniqueConstraint('budget_id', 'code'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey('budgets.id', ondelete='CASCADE'))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('lines.id'), nullable=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(12))  # ANALYTICAL / SYNTHETIC
    formula: Mapped[str | None] = mapped_column(String(500), nullable=True)
    position: Mapped[int] = mapped_column(default=0)


class Value(Base):
    __tablename__ = 'values'
    __table_args__ = (UniqueConstraint('line_id', 'period_id', 'measure', 'currency'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey('lines.id', ondelete='CASCADE'))
    period_id: Mapped[int] = mapped_column(ForeignKey('periods.id', ondelete='CASCADE'))
    measure: Mapped[str] = mapped_column(String(24))
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))


class FxRate(Base):
    __tablename__ = 'fx_rates'
    __table_args__ = (UniqueConstraint('budget_id', 'period_id', 'from_currency', 'to_currency'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey('budgets.id', ondelete='CASCADE'))
    period_id: Mapped[int] = mapped_column(ForeignKey('periods.id', ondelete='CASCADE'))
    from_currency: Mapped[str] = mapped_column(String(3))
    to_currency: Mapped[str] = mapped_column(String(3))
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 12))



MEASURES = {'BUDGET', 'ACTUAL', 'RESERVED', 'COMMITTED', 'CONTINGENCED', 'BLOCKED'}
