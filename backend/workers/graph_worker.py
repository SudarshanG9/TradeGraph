from backend.events.dispatcher import DerivedWorker


class GraphWorker(DerivedWorker):
    def __init__(self,store,dispatcher):
        self.store=store
        super().__init__('neo4j',self.handle,dispatcher)

    def handle(self,event):
        if event is None:
            self.store.initialize()
            self.store.rebuild()
            self.store.retention()
        else:
            self.store.apply(event)
