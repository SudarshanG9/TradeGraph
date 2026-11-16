"""Version 1 notification protocol. Financial data always comes from HTTP/SQL."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

EventType = Literal['book.changed','trade.committed','order.changed','account.changed','simulator.changed','service.degraded','resync.required']


class LiveEvent(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    schema_version: Literal[1]=1
    type: EventType
    epoch: str
    sequence: int = Field(ge=1)
    published_at: str
    instrument_id: int | None=None
    version: int | None=None
    execution_id: str | None=None


def envelope(kind, epoch, sequence, **fields):
    return LiveEvent(type=kind,epoch=epoch,sequence=sequence,
        published_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),**fields).model_dump(exclude_none=True)


class Subscription(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    type: Literal['subscribe','unsubscribe','pong']
    instrument_ids: list[int] = Field(default_factory=list,max_length=8)
