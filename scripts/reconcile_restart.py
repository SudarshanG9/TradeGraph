"""Read-only restart diagnostics. Never takes ownership or changes orders/balances."""
import json
from backend.config import Settings
from backend.stores.postgres import Database
from backend.risk.restart_safety import diagnose


if __name__=='__main__':
    print(json.dumps(diagnose(Database(Settings.from_env())),indent=2))
