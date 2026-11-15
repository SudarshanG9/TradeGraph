from backend.events.dispatcher import DerivedWorker


class RegimeWorker(DerivedWorker):
    def __init__(self,store,dispatcher):
        self.store=store
        self.books={}
        super().__init__('regimes',self.handle,dispatcher)

    def record_book(self,snapshot):
        self.books[snapshot['instrument_id']]=snapshot

    def publish_settled(self,event):
        self.publish((event,self.books.get(event.instrument_id,{'bids':[],'asks':[]})))

    def handle(self,payload):
        event,snapshot=payload
        self.store.capture(event.instrument_id,snapshot)
