from backend.events.dispatcher import ReplaceableWorker


class CacheWorker(ReplaceableWorker):
    def __init__(self,database,store,dispatcher):
        self.database,self.store=database,store
        self.symbols={}
        self.after_apply=None
        super().__init__('redis',self.handle,dispatcher,key=lambda s:s['instrument_id'],
            newer=lambda new,old:new['epoch']!=old['epoch'] or new['version']>old['version'])

    def handle(self,snapshot):
        instrument=snapshot['instrument_id']
        if instrument not in self.symbols:
            self.symbols[instrument]=self.database.query('SELECT symbol FROM instrument WHERE id=%s',(instrument,))[0]['symbol']
        applied=self.store.apply(self.symbols[instrument],snapshot['bids'],snapshot['asks'],version=snapshot['version'],epoch=snapshot['epoch'],as_of=snapshot['as_of'])

        if applied and self.after_apply is not None:self.after_apply(snapshot)
