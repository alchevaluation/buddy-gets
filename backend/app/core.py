from __future__ import annotations

import ast
import re
from decimal import Decimal
from typing import Callable

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


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
TOKEN = re.compile(r'\[([A-Za-z0-9_.-]+)\]')


def evaluate_formula(expression: str, resolve: Callable[[str], Decimal]) -> Decimal:
    """Evaluate only +, -, *, /, parentheses, numeric constants and [line_code] references."""
    references: dict[str, str] = {}

    def sub(match: re.Match[str]) -> str:
        key = f'_ref{len(references)}'
        references[key] = match.group(1)
        return key

    source = TOKEN.sub(sub, expression)
    try:
        root = ast.parse(source, mode='eval')
    except SyntaxError as exc:
        raise ValueError('Invalid formula syntax') from exc

    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name) and node.id in references:
            return resolve(references[node.id])
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = visit(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return a + b
            if isinstance(node.op, ast.Sub): return a - b
            if isinstance(node.op, ast.Mult): return a * b
            if b == 0: raise ValueError('Division by zero')
            return a / b
        raise ValueError('Unsupported formula operation')

    return visit(root)


def matrix(session: Session, budget_id: int, measure: str, target_currency: str) -> dict:
    budget = session.get(Budget, budget_id)
    if budget is None:
        raise ValueError('Budget not found')
    if measure not in MEASURES:
        raise ValueError('Unknown measure')
    periods = list(session.scalars(select(Period).where(Period.budget_id == budget_id).order_by(Period.position)))
    lines = list(session.scalars(select(Line).where(Line.budget_id == budget_id).order_by(Line.position, Line.id)))
    by_code = {line.code: line for line in lines}
    by_parent: dict[int, list[Line]] = {}
    for line in lines:
        if line.parent_id is not None:
            by_parent.setdefault(line.parent_id, []).append(line)
    result = []
    for period in periods:
        values = list(session.scalars(select(Value).where(Value.period_id == period.id, Value.measure == measure)))
        rates = list(session.scalars(select(FxRate).where(FxRate.budget_id == budget_id, FxRate.period_id == period.id)))
        exchange = {(r.from_currency, r.to_currency): r.rate for r in rates}
        cells: dict[str, Decimal] = {}
        visiting: set[str] = set()

        def resolve(code: str) -> Decimal:
            if code in cells: return cells[code]
            if code in visiting: raise ValueError('Circular formula reference')
            line = by_code.get(code)
            if line is None: raise ValueError(f'Unknown line reference: {code}')
            visiting.add(code)
            try:
                if line.kind == 'ANALYTICAL':
                    total = Decimal('0')
                    for cell in values:
                        if cell.line_id != line.id: continue
                        if cell.currency == target_currency:
                            total += cell.amount
                        else:
                            rate = exchange.get((cell.currency, target_currency))
                            if rate is None: raise ValueError(f'Missing FX rate {cell.currency}/{target_currency} for {period.name}')
                            total += cell.amount * rate
                elif line.formula:
                    total = evaluate_formula(line.formula, resolve)
                else:
                    total = sum((resolve(child.code) for child in by_parent.get(line.id, [])), Decimal('0'))
                cells[code] = total
                return total
            finally:
                visiting.remove(code)

        for line in lines:
            resolve(line.code)
        result.append({'period_id': period.id, 'period': period.name, 'values': {key: str(v) for key, v in cells.items()}})
    return {'budget_id': budget_id, 'measure': measure, 'currency': target_currency, 'periods': result}
