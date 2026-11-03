from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import Base, Budget, FxRate, Line, MEASURES, Period, Value, matrix
from .core.database import make_engine, make_session_factory


class BudgetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    presentation_currency: str = Field(default='BRL', pattern=r'^[A-Z]{3}$')


class PeriodIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    starts_on: date
    ends_on: date
    position: int = Field(ge=0)

    @model_validator(mode='after')
    def valid_dates(self):
        if self.starts_on > self.ends_on: raise ValueError('End date before start date')
        return self


class LineIn(BaseModel):
    code: str = Field(min_length=1, max_length=60, pattern=r'^[A-Za-z0-9_.-]+$')
    name: str = Field(min_length=1, max_length=120)
    kind: Literal['ANALYTICAL', 'SYNTHETIC']
    parent_id: int | None = None
    formula: str | None = Field(default=None, max_length=500)
    position: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def valid_formula(self):
        if self.kind == 'ANALYTICAL' and self.formula:
            raise ValueError('Analytical lines cannot have formulas')
        return self


class ValueIn(BaseModel):
    line_id: int
    period_id: int
    measure: str
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    amount: Decimal = Field(max_digits=20, decimal_places=4)


class RateIn(BaseModel):
    period_id: int
    from_currency: str = Field(pattern=r'^[A-Z]{3}$')
    to_currency: str = Field(pattern=r'^[A-Z]{3}$')
    rate: Decimal = Field(gt=0, max_digits=24, decimal_places=12)


def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url)
    SessionLocal = make_session_factory(engine)
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        Base.metadata.create_all(engine)  # Bootstrap MVP only; replace with Alembic migrations later.
        yield

    api = FastAPI(title='Buddy-Gets API', version='0.1.0', lifespan=lifespan)

    def db():
        with SessionLocal() as session:
            yield session

    def owned_budget(session: Session, budget_id: int) -> Budget:
        budget = session.get(Budget, budget_id)
        if budget is None: raise HTTPException(404, 'Budget not found')
        return budget

    @api.get('/health')
    def health():
        return {'status': 'ok'}

    @api.post('/budgets', status_code=201)
    def add_budget(payload: BudgetIn, session: Session = Depends(db)):
        item = Budget(**payload.model_dump())
        session.add(item); session.commit(); session.refresh(item)
        return {'id': item.id, 'name': item.name, 'presentation_currency': item.presentation_currency}

    @api.get('/budgets')
    def list_budgets(session: Session = Depends(db)):
        return [{'id': b.id, 'name': b.name, 'presentation_currency': b.presentation_currency} for b in session.scalars(select(Budget))]

    @api.post('/budgets/{budget_id}/periods', status_code=201)
    def add_period(budget_id: int, payload: PeriodIn, session: Session = Depends(db)):
        owned_budget(session, budget_id)
        item = Period(budget_id=budget_id, name=payload.name, starts_on=payload.starts_on.isoformat(), ends_on=payload.ends_on.isoformat(), position=payload.position)
        session.add(item)
        try: session.commit()
        except Exception: session.rollback(); raise HTTPException(409, 'Duplicate position or invalid period')
        return {'id': item.id}

    @api.delete('/budgets/{budget_id}/periods/{period_id}', status_code=204)
    def delete_period(budget_id: int, period_id: int, session: Session = Depends(db)):
        owned_budget(session, budget_id)
        item = session.get(Period, period_id)
        if not item or item.budget_id != budget_id: raise HTTPException(404, 'Period not found')
        if session.scalar(select(Value.id).where(Value.period_id == period_id).limit(1)):
            raise HTTPException(409, 'Period contains values; deletion denied')
        if session.scalar(select(FxRate.id).where(FxRate.period_id == period_id).limit(1)):
            raise HTTPException(409, 'Period contains FX rates; deletion denied')
        session.delete(item); session.commit()

    @api.post('/budgets/{budget_id}/lines', status_code=201)
    def add_line(budget_id: int, payload: LineIn, session: Session = Depends(db)):
        owned_budget(session, budget_id)
        if payload.parent_id is not None:
            parent = session.get(Line, payload.parent_id)
            if parent is None or parent.budget_id != budget_id or parent.kind != 'SYNTHETIC':
                raise HTTPException(422, 'Parent must be a synthetic line of same budget')
        if session.scalar(select(Line.id).where(Line.budget_id == budget_id, Line.code == payload.code)):
            raise HTTPException(409, 'Line code already exists')
        item = Line(budget_id=budget_id, **payload.model_dump())
        session.add(item); session.commit(); session.refresh(item)
        return {'id': item.id}

    @api.put('/budgets/{budget_id}/values')
    def put_value(budget_id: int, payload: ValueIn, session: Session = Depends(db)):
        owned_budget(session, budget_id)
        line, period = session.get(Line, payload.line_id), session.get(Period, payload.period_id)
        if not line or line.budget_id != budget_id or line.kind != 'ANALYTICAL':
            raise HTTPException(422, 'Line must be analytical and belong to budget')
        if not period or period.budget_id != budget_id:
            raise HTTPException(422, 'Period does not belong to budget')
        if payload.measure not in MEASURES: raise HTTPException(422, 'Unknown measure')
        lookup = select(Value).where(Value.line_id == payload.line_id, Value.period_id == payload.period_id, Value.measure == payload.measure, Value.currency == payload.currency)
        value = session.scalar(lookup)
        if value: value.amount = payload.amount
        else: session.add(Value(**payload.model_dump()))
        session.commit()
        return {'saved': True}

    @api.put('/budgets/{budget_id}/rates')
    def put_rate(budget_id: int, payload: RateIn, session: Session = Depends(db)):
        owned_budget(session, budget_id)
        period = session.get(Period, payload.period_id)
        if not period or period.budget_id != budget_id: raise HTTPException(422, 'Period does not belong to budget')
        lookup = select(FxRate).where(FxRate.budget_id == budget_id, FxRate.period_id == payload.period_id, FxRate.from_currency == payload.from_currency, FxRate.to_currency == payload.to_currency)
        item = session.scalar(lookup)
        if item: item.rate = payload.rate
        else: session.add(FxRate(budget_id=budget_id, **payload.model_dump()))
        session.commit()
        return {'saved': True}

    @api.get('/budgets/{budget_id}/matrix')
    def get_matrix(budget_id: int, measure: str = 'BUDGET', currency: str | None = None, session: Session = Depends(db)):
        budget = owned_budget(session, budget_id)
        try: return matrix(session, budget_id, measure, currency or budget.presentation_currency)
        except (ValueError, ArithmeticError) as exc: raise HTTPException(422, str(exc)) from exc

    return api


app = create_app()
