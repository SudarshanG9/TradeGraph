from backend.events.dispatcher import DerivedWorker


class RegimeWorker(DerivedWorker):
    def __init__(self,store,dispatcher):
        self.store=store
        self.books={}
        self.rejected={}
        super().__init__('regimes',self.handle,dispatcher)

    def record_book(self,snapshot):
        self.books[snapshot['instrument_id']]=snapshot

    def publish_settled(self,event):
        payload=self.rejected.get(event.event_id)
        if payload is None:
            payload=(event,self.books.get(event.instrument_id,{'bids':[],'asks':[]}))
        try:
            self.publish(payload)
        except RuntimeError:
            self.rejected[event.event_id]=payload
            raise
        else:
            self.rejected.pop(event.event_id,None)

    def handle(self,payload):
        event,snapshot=payload
        self.store.capture(event.instrument_id,snapshot)
