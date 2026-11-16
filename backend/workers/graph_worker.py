from backend.events.dispatcher import ReplaceableWorker


class GraphWorker(ReplaceableWorker):
    def __init__(self,store,dispatcher):
        self.store=store
        self.ready=False
        super().__init__('neo4j',self.handle,dispatcher,
            key=lambda event:None if event is None else (event.buy_trader_id,event.sell_trader_id))

    def handle(self,event):
        if event is None:
            self.store.initialize()
            self.store.rebuild()
            self.store.retention()
            self.ready=True
        else:
            self.store.apply(event)
