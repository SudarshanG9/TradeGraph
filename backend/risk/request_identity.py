"""Durable financial request identity; no expiry or process-lifetime key limit."""
import hashlib
import json


class DuplicateRequest(Exception):
    """The same trader/key was previously bound to a different validated order."""


def request_hash(request):
    # Explicit validated fields and exact integers, independent of JSON formatting.
    fields = [request.instrument_id, request.side, request.price_ticks, request.quantity]
    return hashlib.sha256(json.dumps(fields, separators=(',', ':')).encode('ascii')).hexdigest()


class RequestIdentityStore:
    def __init__(self, database):
        self.database = database

    def lookup(self, trader_id, key):
        return self.database.request_identity(trader_id, key)

    @staticmethod
    def verify(identity, request):
        if identity['request_hash'] != request_hash(request):
            raise DuplicateRequest('Request key conflicts with the original order')
        return {'id': identity['order_id'], 'created_at': identity['accepted_at'], '_replayed': True}
