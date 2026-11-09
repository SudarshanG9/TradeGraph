# TradeGraph ER Diagram — Day 1

## 13 physical PostgreSQL tables

```mermaid
erDiagram
    USER_ACCOUNT ||--o| TRADER : authenticates
    DESK o|--o{ DESK : parent_of
    DESK o|--o{ TRADER : contains
    TRADER o|--o{ DESK : manages
    TRADER ||--o| KYC_PROFILE : has
    TRADER ||--o| MARGIN_ACCOUNT : owns
    FEE_TIER ||--o{ MARGIN_ACCOUNT : assigns
    TRADER ||--o{ ORDER : submits
    INSTRUMENT ||--o{ ORDER : receives
    ORDER ||..o| ORDER_HISTORY : archives_to
    TRADER ||--o{ ORDER_HISTORY : submitted
    INSTRUMENT ||--o{ ORDER_HISTORY : traded_on
    TRADER ||--o{ EXECUTION : buys_in
    TRADER ||--o{ EXECUTION : sells_in
    INSTRUMENT ||--o{ EXECUTION : executes
    TRADER ||--o{ POSITION : holds
    INSTRUMENT ||--o{ POSITION : identifies
    INSTRUMENT o|--o{ MARKET_DISCLOSURE : references
    INSTRUMENT ||--o{ REGIME_SNAPSHOT : snapshots

    USER_ACCOUNT {
      uuid id PK
      string email UK
      string password_hash
      string role
      timestamptz created_at
    }
    DESK {
      int id PK
      string name UK
      int parent_desk_id FK
      uuid manager_trader_id FK
    }
    TRADER {
      uuid id PK
      uuid user_account_id FK,UK
      int desk_id FK
      string full_name
      timestamptz created_at
    }
    KYC_PROFILE {
      uuid trader_id PK,FK
      string pan_hash
      boolean verified
      timestamptz verified_at
    }
    FEE_TIER {
      int id PK
      string tier_name UK
      numeric maker_fee_bps
      numeric taker_fee_bps
    }
    MARGIN_ACCOUNT {
      uuid trader_id PK,FK
      bigint cash_balance
      bigint escrow_balance
      int fee_tier_id FK
      timestamptz updated_at
    }
    INSTRUMENT {
      int id PK
      string symbol UK
      int tick_size
      int lot_size
      boolean is_active
    }
    ORDER {
      bigint id PK
      uuid trader_id FK
      int instrument_id FK
      string side
      bigint price_ticks
      bigint quantity
      bigint filled_quantity
      string status
      timestamptz created_at
      timestamptz updated_at
    }
    ORDER_HISTORY {
      bigint id PK
      uuid trader_id FK
      int instrument_id FK
      string side
      bigint price_ticks
      bigint quantity
      bigint filled_quantity
      string status
      timestamptz created_at
      timestamptz updated_at
      timestamptz archived_at
    }
    EXECUTION {
      bigint id PK
      int instrument_id FK
      bigint buy_order_id
      bigint sell_order_id
      uuid buy_trader_id FK
      uuid sell_trader_id FK
      bigint price_ticks
      bigint quantity
      timestamptz executed_at
    }
    POSITION {
      uuid trader_id PK,FK
      int instrument_id PK,FK
      bigint net_quantity
      bigint realized_pnl
      timestamptz updated_at
    }
    MARKET_DISCLOSURE {
      bigint id PK
      int instrument_id FK
      string title
      text body
      tsvector body_tsv
      timestamptz published_at
    }
    REGIME_SNAPSHOT {
      bigint id PK
      int instrument_id FK
      timestamptz captured_at
      vector6 features
    }
```

## Relational cardinality and implementation notes

- A `USER_ACCOUNT` may have one `TRADER`. Compliance administrators can have a login on its own.
- `DESK.parent_desk_id` gives each desk an optional parent and lets a parent have multiple children.
- A desk can have multiple traders. A trader's desk assignment is optional.
- A desk can have one manager. A trader can manage several desks.
- Each trader can have one `KYC_PROFILE` and one `MARGIN_ACCOUNT`. The demo seeder creates both.
- `POSITION` links traders to instruments with the composite key `(trader_id, instrument_id)`.
- `EXECUTION` references both counterparties and retains the buy and sell order IDs after archival.
- The dashed archival edge shows how `ORDER_HISTORY` retains the original order ID. Archive rows have foreign keys to the trader and instrument.
