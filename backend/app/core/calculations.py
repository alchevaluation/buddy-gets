from __future__ import annotations

import ast
import re
from decimal import Decimal
from typing import Callable
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Budget, Period, Line, Value, FxRate, MEASURES

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
