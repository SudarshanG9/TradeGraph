"""Database transaction boundary for immutable fill retries."""
def settle(database, event):
    return database.settle(event)
