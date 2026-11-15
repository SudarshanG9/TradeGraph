from backend.events.dispatcher import DerivedWorker


class CacheWorker(DerivedWorker):
    def __init__(self,database,store,dispatcher):
        self.database,self.store=database,store
        self.symbols={}
        super().__init__('redis',self.handle,dispatcher)

    def handle(self,snapshot):
        instrument=snapshot['instrument_id']
        if instrument not in self.symbols:
            self.symbols[instrument]=self.database.query('SELECT symbol FROM instrument WHERE id=%s',(instrument,))[0]['symbol']
        self.store.apply(self.symbols[instrument],snapshot['bids'],snapshot['asks'],version=snapshot['version'],epoch=snapshot['epoch'],as_of=snapshot['as_of'])
