from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core import evaluate_formula
from decimal import Decimal


@pytest.fixture
def client(tmp_path: Path):
    with TestClient(create_app(f'sqlite:///{tmp_path / "test.db"}')) as test:
        yield test


def budget(client):
    r = client.post('/budgets', json={'name': 'Test', 'presentation_currency': 'BRL'})
    assert r.status_code == 201
    return r.json()['id']


def period(client, budget_id, name, position):
    r = client.post(f'/budgets/{budget_id}/periods', json={'name': name, 'starts_on': '2027-01-01', 'ends_on': '2027-01-31', 'position': position})
    assert r.status_code == 201
    return r.json()['id']


def line(client, bid, code, kind, parent_id=None, formula=None):
    r = client.post(f'/budgets/{bid}/lines', json={'code': code, 'name': code, 'kind': kind, 'parent_id': parent_id, 'formula': formula})
    assert r.status_code == 201, r.text
    return r.json()['id']


def value(client, bid, lid, pid, amount, measure='BUDGET', currency='BRL'):
    return client.put(f'/budgets/{bid}/values', json={'line_id': lid, 'period_id': pid, 'amount': str(amount), 'measure': measure, 'currency': currency})


def test_budget_and_independent_categories(client):
    b = budget(client)
    p = period(client, b, 'P1', 0)
    l = line(client, b, 'SAL', 'ANALYTICAL')
    assert value(client, b, l, p, 100).status_code == 200
    assert value(client, b, l, p, 60, 'ACTUAL').status_code == 200
    assert value(client, b, l, p, 100, 'BUDGET').status_code == 200
    assert client.get(f'/budgets/{b}/matrix?measure=BUDGET').json()['periods'][0]['values']['SAL'] == '100.0000'
    assert client.get(f'/budgets/{b}/matrix?measure=ACTUAL').json()['periods'][0]['values']['SAL'] == '60.0000'
    assert client.delete(f'/budgets/{b}/periods/{p}').status_code == 409


def test_rollup_and_formula(client):
    b = budget(client); p = period(client, b, 'P1', 0)
    revenue = line(client, b, 'REV', 'SYNTHETIC')
    a = line(client, b, 'A', 'ANALYTICAL', revenue)
    expense = line(client, b, 'EXP', 'ANALYTICAL')
    line(client, b, 'PROFIT', 'SYNTHETIC', formula='[REV] - [EXP]')
    value(client, b, a, p, 150)
    value(client, b, expense, p, 40)
    result = client.get(f'/budgets/{b}/matrix').json()['periods'][0]['values']
    assert Decimal(result['REV']) == 150
    assert Decimal(result['PROFIT']) == 110


def test_currency_conversion(client):
    b = budget(client); p = period(client, b, 'P1', 0)
    l = line(client, b, 'SAL', 'ANALYTICAL')
    value(client, b, l, p, 20, currency='EUR')
    assert client.get(f'/budgets/{b}/matrix').status_code == 422
    assert client.put(f'/budgets/{b}/rates', json={'period_id': p, 'from_currency': 'EUR', 'to_currency': 'BRL', 'rate': '6.25'}).status_code == 200
    result = client.get(f'/budgets/{b}/matrix').json()
    assert Decimal(result['periods'][0]['values']['SAL']) == 125


def test_cross_budget_guard(client):
    a, b = budget(client), budget(client)
    pa = period(client, a, 'P1', 0)
    lb = line(client, b, 'B', 'ANALYTICAL')
    assert value(client, a, lb, pa, 200).status_code == 422
    assert client.post(f'/budgets/{a}/lines', json={'code': 'BAD', 'name': 'Bad', 'kind': 'ANALYTICAL', 'parent_id': lb}).status_code == 422


def test_formula_is_safe():
    assert evaluate_formula('[A] * 2 + 3', lambda code: Decimal('10')) == 23
    with pytest.raises(ValueError):
        evaluate_formula('__import__("os").system("echo unsafe")', lambda code: Decimal(0))
