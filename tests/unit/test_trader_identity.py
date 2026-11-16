import json
from uuid import uuid4
import psycopg
import pytest
from backend.stores.trader_identity import credentials,trader_role


def test_private_trader_credentials_fail_closed_on_missing_mismatch_or_broad_permissions(tmp_path):
    trader=uuid4();other=uuid4();path=tmp_path/'private-identities.json'
    path.write_text(json.dumps({'traders':{str(trader):{'user':trader_role(trader),'password':'unit-test-private-password'}}}))
    path.chmod(0o600)
    assert credentials(path,trader)==(trader_role(trader),'unit-test-private-password')
    with pytest.raises(psycopg.OperationalError):credentials(path,other)
    path.chmod(0o644)
    with pytest.raises(psycopg.OperationalError):credentials(path,trader)
    path.chmod(0o600)
    path.write_text(json.dumps({'traders':{str(trader):{'user':trader_role(other),'password':'unit-test-private-password'}}}))
    with pytest.raises(psycopg.OperationalError):credentials(path,trader)


def test_wrong_password_authentication_is_rejected_if_server_uses_trust(monkeypatch):
    from backend.stores.trader_identity import verify_password_authentication
    from types import SimpleNamespace
    closed=[]
    monkeypatch.setattr(psycopg,'connect',lambda **kwargs:SimpleNamespace(close=lambda:closed.append(True)))
    with pytest.raises(RuntimeError,match='incorrect passwords'):verify_password_authentication('test',5432,'test','test')
    assert closed==[True]
    def denied(**kwargs):raise psycopg.errors.InvalidPassword('synthetic password rejection')
    monkeypatch.setattr(psycopg,'connect',denied)
    assert verify_password_authentication('test',5432,'test','test')


def test_handshake_state_omission_does_not_accept_network_errors(monkeypatch):
    from backend.stores.trader_identity import verify_password_authentication
    def network(**kwargs):raise psycopg.OperationalError('connection refused')
    monkeypatch.setattr(psycopg,'connect',network)
    with pytest.raises(RuntimeError,match='could not be verified'):verify_password_authentication('test',5432,'test','test')
    def password(**kwargs):raise psycopg.OperationalError('password authentication failed for user "test"')
    monkeypatch.setattr(psycopg,'connect',password)
    assert verify_password_authentication('test',5432,'test','test')
