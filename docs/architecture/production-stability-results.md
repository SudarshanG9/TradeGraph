# Production transport and stability results

Verification date: 2026-11-17 (Asia/Kolkata). Branch:
`codex/final-recovery-production-hardening`.

## Environment and boundaries

Apple M1, eight logical CPUs, 8 GiB RAM, arm64 macOS. Native PostgreSQL 17.12,
Redis 8.10.2, Neo4j 2026.09.0, Python 3.13.0, Node 22.17.1, Next 16.4.6,
Caddy 2.11.9. Native dedicated SCRAM PostgreSQL clusters and dedicated Redis
processes were created under private temporary directories. The configured user's
financial database was never used. Neo4j interruptions use a test-app handler fault
scoped to newly created test traders; the shared Neo4j service was never stopped.

Actual Caddy validation and TLS/WSS tests passed with a production Next build and
Uvicorn. The local certificate is explicitly trusted by Python clients, and the
browser pins the test certificate public key. The OS trust store is untouched.
Test ports/certificate differ from public deployment; public DNS, ACME issuance,
internet latency and deployment-specific firewall rules are NOT_VERIFIED.

## Capacity

Actual 10/50/100-client WSS scenarios: 4 tests passed in 23.97 seconds. Each case
includes trading via authenticated BFF sessions, slow reception, fresh-ticket
reconnect bursts and invalid tickets. All disconnected socket tasks were released.
No cross-user private event leakage was observed. Credential setup for capacity
uses synthetic signed JWTs and the real internal ticket endpoint, with all WSS
identity checks enabled. Actual password login is covered separately over HTTPS.

| Concurrent WSS clients | Establish p95 ms | Notification p95 ms | Financial transaction p95 ms | Reconnected | Tasks left |
|---|---:|---:|---:|---:|---:|
| 10 | 145.31 | 34.27 | 12.91 | 10 | 0 |
| 50 | 190.16 | 202.45 | 14.37 | 50 | 0 |
| 100 | 154.52 | 282.22 | 14.32 | 100 | 0 |

Notification measurements include slow clients (max delay ~3.2 seconds). Sampled
RSS was ~103–112 MiB backend, ~135–145 MiB Next and ~49–62 MiB Caddy. Samples of
2–5 PostgreSQL connections and zero queued messages are instantaneous observations,
not peak limits. CPU samples include startup/bcrypt and cannot establish a sustained
CPU ceiling. Deterministic fanout overload separately verifies bounded overflow.
The 1024 global limit is unchanged and was not measured with 1024 real clients.
Raw capacity evidence is in `recovery-hardening-evidence/websocket-capacity.json`.

## Sustained test

A 35.08-second smoke run completed 26 executions with three real browser sessions,
nine browser refreshes and 224 observed frames, no order errors and no browser
recovery errors. It was a harness check, not the long-duration acceptance test.

The first continuous run completed **1813.43 seconds** (30 minutes plus shutdown
convergence), **1581 executions** and **3162 BFF order requests**. It had no order
errors or cross-user private invalidations. Three browser sessions completed 516
refreshes and observed 14,350 frames, with no recovery errors. All required durable
publication for the fixture drained; final active orders, escrow/position/volume
mismatches, duplicate IDs, execution/order mismatches and missing intents were zero.
All accepted sockets and their tasks were released. The independent read-only SQL
auditor checked 320 snapshots and all 1581 execution records, ending with exact
cash-plus-escrow 36,838 (= 40,000 minus 3,162 fees), zero escrow, zero net position
sum and zero gross realized PnL.

| Interruption | Mode | Measured interruption/restart seconds |
|---|---|---:|
| Neo4j | Scoped test-handler fault, shared service kept running | 3.01 |
| Redis | Owned isolated service stopped and restarted | 3.09 |
| Next | Owned production process restarted | 0.46 |
| Caddy | Owned actual TLS proxy restarted | 0.24 |
| FastAPI | Restart gated on terminal matching state and invariants | 1.10 |

The run measured BFF order p95 110.96 ms, WSS establishment p95 81.13 ms and
notification p95 4.01 ms across the last 20,000 retained timing samples. Financial
transaction p95 was 42.50 ms across 623 samples since the backend restart. Metrics
are bounded samples, not all-history telemetry. There were 265 successful socket
connections, zero dropped server notifications and zero final settlement queue
items. Expected interruption observations included 16 closed connections and 39
failed ticket/auth requests; these were retried with existing authorization intact.

There were 174 process/queue samples. Maximum sampled RSS: backend 107.41 MiB,
Next 152.69 MiB, Caddy 52.22 MiB; final values were 58.13/142.25/36.59 MiB.
No monotonic unbounded RSS/queue growth appeared in this window. CPU samples include
startup, cryptography and simultaneous regression work: backend p95 216.4% of one
core on an eight-core host, Next 39.9%, Caddy 11.1%. This is a shared-host operational
measurement, not a throughput or CPU ceiling. Browser/DB/Neo4j whole-host memory was
not included in those per-process RSS figures.

First-run limitations: additive observation metadata was installed during the run
and loaded on the planned backend restart. It was a rolling recovery exercise,
not a single-revision benchmark. An intended slow raw receiver was absent after
the seven-client/three-browser allocation changed its index. Actual capacity cases
did include slow readers. The second completed run below corrects the receiver.
Evidence: `recovery-hardening-evidence/stability-rolling-30min.json` and
`recovery-hardening-evidence/accounting-rolling-30min.json`. Resource evidence
summarizes repeated settlement arrays rather than duplicating cumulative samples.


## Final slow-receiver run

**PASS: 1810.30 seconds, 1582 executions and 3164 BFF order requests.** This run
included the intentional 400 ms per-frame delay on raw receiver 6, seven raw WSS
clients and three actual browser sessions. Three browsers completed 516 refreshes
and received 14,375 frames with no browser recovery errors. There were no order
errors or cross-user private invalidations. All five interruption scenarios
recovered; their measured interruption/restart times were 3.00 sec scoped Neo4j,
3.06 sec isolated Redis, 0.46 sec Next, 0.13 sec Caddy and 1.33 sec FastAPI.

| Measurement | Actual result |
|---|---:|
| BFF order latency p50 / p95 / max | 62.78 / 103.26 / 233.30 ms |
| WSS establishment p95 | 73.76 ms |
| Notification latency p50 / p95 / max, including slow receiver | 1.33 / 6064.07 / 27656.57 ms |
| Financial transaction p95 / max since backend restart (622 samples) | 36.07 / 67.37 ms |
| Successful socket connections | 258 |
| Server queue overflow/drop counter | 0 |
| Final clients / socket tasks / settlement queue | 0 / 0 / 0 |
| Final financial/invariant/publication mismatches | 0 |

The deliberately slow receiver explains the notification tail; settlement and
browser resynchronization continued. Zero server overflow counts do not mean
end-to-end guaranteed notification delivery: intentional disconnections still
require authoritative snapshots. Notifications remain best effort.

The independent read-only auditor checked **354 snapshots** and every one of the
**1582 canonical executions**. Final cash plus escrow was **36,836**, exactly
40,000 minus 3,164 fees; final escrow, position sum and gross realized PnL were zero.
Both actors' final net positions were zero because the trade count was even.
All fixture publication intents drained before cleanup. Expected interruption
observations were 12 closed sockets and 12 rejected/unavailable ticket requests;
existing authorization was retained and clients reconnected.

Across 175 resource samples, maximum RSS was 91.67 MiB backend, 179.38 MiB Next and
52.48 MiB Caddy; final RSS was 51.47/146.77/35.97 MiB. CPU p95 was 221.9%/40.2%/11.2%
of one core respectively on the eight-core host. These samples include startup and
shared-host regression work and do not establish deployment capacity ceilings.
No runaway queue or monotonic memory trend was observed in the measured window;
process restarts and OS memory management limit leak conclusions.

The first and second runs provide **3623.74 measured seconds** and **3163 total
executions**, across two separate runs. This is more than 60 minutes cumulatively,
not one uninterrupted hour or evidence of days/weeks of uptime. The second run
loaded the separately tested historical-retention callback on its planned backend
restart; its current-trade path and financial/transport behavior were unchanged.
No additional financial or transport implementation changed during that run.
Evidence: `recovery-hardening-evidence/stability-final-30min.json` and
`recovery-hardening-evidence/accounting-final-30min.json`.

## Remaining limits and cleanup

Automatic active-order recovery and torn-lease fencing remain blocked by the absent
admission/fill journal and transaction-level owner-generation protocol. Historical
regime observations with missing inputs or unknown ordering are preserved and
reported, not invented. The current tested replay paths do not prove safe remote
writes from an old owner after a torn lease. Public DNS/ACME/firewall deployment and
1024-client real capacity remain NOT_VERIFIED. Neo4j fault injection was scoped;
the shared Neo4j service itself was never stopped.

After both runs and all regressions, read-only checks confirmed zero active matching
owners and unresolved orders. Only the two dedicated test PostgreSQL/Redis stacks
were stopped. Owned Caddy, Next, FastAPI and browser processes were shut down by the
harnesses; private evidence/data files were retained. No configured financial
PostgreSQL or shared Neo4j service was stopped or reset.
