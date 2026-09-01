# FleetGuard AI

Predictive maintenance for commercial truck fleets.

Every modern truck already streams around two hundred sensor signals that
contain early warning of component failure. FleetGuard AI turns *"the truck
broke down"* into *"this component will likely fail in 17 days — order the part
now and book the slot."*

It answers four questions, and every layer exists to answer one of them:

1. **Which telematics signals reliably precede failure of a given component?**
   → the correlation engine and Rule Studio
2. **How likely is this component on this truck to fail soon?**
   → the health index and risk tiers
3. **How much useful life is left, in kilometres and days?**
   → the RUL projection
4. **Can a non-technical fleet manager just ask, in plain English?**
   → the grounded assistant

Scale of the seeded dataset: **6 customers, 600 vehicles, 8 components, 52
weeks**, with **32 API routes** and **18 assistant tools**.

---

## Quick start

You need Docker and Docker Compose. Nothing else.

```bash
cp fleetguard-backend/.env.example fleetguard-backend/.env
# fill in MYSQL_PASSWORD and JWT_SECRET; LLM_API_KEY only if you want the assistant
docker compose up -d
docker compose logs -f backend
```

The backend container runs migrations, then seeds and scores **only if the
database is empty**, so restarts are cheap. The first run takes a few minutes —
most of it is the scoring pass.

When it settles:

| URL | What it is |
|---|---|
| <http://localhost:5173> | the product |
| <http://localhost:8000/docs> | interactive OpenAPI, all 32 routes |
| <http://localhost:8000/api/health> | `{"status":"ok", ...}` |

Sign in with any of the three demo accounts below. The password for all three
is `fleetguard`.

> **Before you trust anything you see on :5173**, confirm you are looking at the
> container and not a stray Vite dev server that has taken the port:
>
> ```bash
> curl -I http://127.0.0.1:5173/     # look for: Server: nginx
> ```
>
> A local `npm run dev` shadows the published port silently, and you will demo a
> stale build without realising.

### Environment variables that actually matter

The full list with comments is in `fleetguard-backend/.env.example`. The ones
without defaults, because guessing them produces a confusing failure later:

| Variable | Why |
|---|---|
| `MYSQL_PASSWORD` | no default; an empty password fails later as access-denied |
| `JWT_SECRET` | no default; required to sign tokens |
| `LLM_API_KEY` | needed only for the assistant. Every other screen works without it. |

`AUTH_ENABLED` defaults to `false`. See [Authentication](#authentication-and-the-two-modes).

---

## The three logins

| Card | Email | Sees | Can |
|---|---|---|---|
| Administrator | `admin@fleetguard.ai` | all 600 vehicles, every customer | everything, including authoring and deploying rules |
| Fleet customer | `fleet@sarthilogistics.in` | 130 vehicles, Sarthi Logistics | acknowledge and dismiss alerts, raise work orders, draft messages; reads rules but cannot change them |
| Read-only viewer | `viewer@bluelinecarriers.in` | 120 vehicles, BlueLine Carriers | nothing that writes |

Password for all three: `fleetguard` (`DEMO_PASSWORD` in `.env`).

These are seeded demo credentials for a POC. `GET /api/auth/demo-accounts`
serves them to the login screen so no credential is hardcoded in the frontend —
and that endpoint **404s the moment `AUTH_ENABLED` is true**, because handing
out working credentials is only defensible while nothing is being protected.

Verified role enforcement, against the live API:

| Request | Administrator | Fleet customer | Read-only viewer |
|---|---|---|---|
| `GET /api/vehicles` | 200, 600 rows | 200, 130 rows | 200, 120 rows |
| same, with `X-Customer-Scope: all` | 200 | **403** | **403** |
| `POST /api/rules` (deploy) | 201 | **403** | **403** |
| `PATCH /api/notifications/{id}` | 200 | 200 | **403** |
| another tenant's VIN | resolves | **404** | **404** |

The disabled buttons in the viewer's UI are a courtesy, not the boundary. The
boundary is `require_write` and `require_rule_author` on the server — which is
why the same call from `curl` is refused too. A cross-tenant VIN answers **404,
not 403**, so the existence of the row is not leaked either.

---

## Run order, and what each step prints

All backend commands run from `fleetguard-backend/` with the virtualenv
activated (`.venv/Scripts/activate` on Windows, `.venv/bin/activate`
elsewhere). Docker does all of this for you; this is the manual path.

```bash
pip install -r requirements.txt
```

### 1. Create the database and migrate

```bash
python -m scripts.manage init-db
```

Creates the schema if absent, then runs `alembic upgrade head`.

### 2. Generate the fleet

```bash
python -m scripts.manage seed
```

**This wipes existing data first.** It generates 600 vehicles across 6
customers with 52 weeks of weekly telemetry, fitment records, job cards,
failures and warranty claims, and writes the hidden ground-truth weights to
`data/planted_weights.json`. It prints the failure count and a check that age
still dominates stress near end of life. Expect roughly 1,400 failures.

Use `--if-empty` to make it idempotent (this is what the container does).

### 3. Score the fleet

```bash
python -m scripts.manage score
```

Deploys a default rule per component and writes a prediction for every
(vehicle, component) pair. Takes about a minute. Also `--if-empty`.

### 4. Validate — the gate

```bash
python -m scripts.manage validate
```

This is the project's scientific credibility: it runs the correlation engine
and compares what it recovered against the planted weights it was **never
shown**. Actual output from a current run:

```
Building feature table...
Feature rows: 249,600
Positive labels: 17,534

Component              N  Recovered     Hit  Rank rho  Missed
-------------------------------------------------------------
Alternator             5    5/5       100%      0.10  -
Radiator Fan           4    4/4       100%      0.60  -
Transmission Fluid     4    4/4       100%      1.00  -
Brake Pads Front       3    3/3       100%      1.00  -
Timing Belt            3    3/3       100%      1.00  -
Turbocharger           3    3/3       100%      0.50  -
Clutch Assembly        3    3/3       100%      0.50  -
Coolant Pump           3    3/3       100%      1.00  -
-------------------------------------------------------------

SIGNAL RECOVERY: 100.0%  (28/28 planted signals)
Weakest component: Alternator at 100%
Target: 90%

PASS - the engine rediscovers the planted relationships.
```

The spec's gate is **≥90%**. The figure is dataset-dependent — the generator
defaults its end date to the current week so demo data always looks fresh, so a
regenerated dataset can land a point or two either side. Pass `--end-date` to
`generate_data.py` for a byte-identical reproduction.

`python -m scripts.manage rebuild` runs steps 1–4 in order.

### 5. Tests

```bash
python -m pytest
```

Expect **283 passed**.

### 6. Serve

```bash
python -m uvicorn app.main:app --reload      # http://localhost:8000/docs
cd ../fleetguard-frontend && npm install && npm run dev
```

---

## Architecture

```
                    ┌──────────────────────────────────────────┐
   browser  ───────▶│  nginx (frontend container)              │
                    │  serves the SPA, proxies /api ───────────┼──▶ FastAPI
                    └──────────────────────────────────────────┘        │
                                                                        ▼
                              ┌──────────────────────────────────────────────┐
                              │  routers/       thin; no business logic      │
                              │      │                                       │
                              │      ▼  get_current_scope()  ── one dependency│
                              │  services/      pure, framework-free         │
                              │      ▲                                       │
                              │      │  the same functions                   │
                              │  agent_tools ── insight_agent / action_agent │
                              └──────────────────────────────────────────────┘
                                                   │
                                                   ▼
                                              MySQL 8
```

**One origin in all three environments.** The app calls `/api/...` on its own
origin; the Vite dev server and the production nginx both proxy it. Set
`VITE_API_BASE_URL` only when the API is genuinely elsewhere.

### Scoping — the single most important piece

Every query in the product — all 32 routes **and** all 18 agent tools — resolves
a frozen `Scope` object through one dependency, `get_current_scope()` in
`app/deps.py`. Its `customer_id` is either `None` (the whole fleet) or exactly
one tenant. Services apply it with `limit_vehicles()`,
`limit_by_customer_column()` or `vin_subquery()`.

`Scope` lives in `app/services/scoping.py` and imports nothing from FastAPI —
deliberately. That is what lets the assistant's tools construct one and call the
identical query functions, and it is the mechanism by which **the assistant and
the dashboard cannot disagree about who may see what**.

A query that touches vehicle data without one of those helpers is a bug, no
matter how correct it looks.

Even `GET /api/filter-options` is scoped, because a filter list built from
whatever rows a page happened to return would silently omit values further down
the result set — and would reveal another tenant's depots.

### Authentication, and the two modes

A presented bearer token **always** drives role and tenant. `AUTH_ENABLED`
decides only what happens when there is *no* token.

| Token? | `AUTH_ENABLED` | What drives scope |
|---|---|---|
| no | `false` (default) | the `X-Customer-Scope` header, set by the UI scope switcher |
| no | `true` | nothing — 401 |
| yes | either | the JWT; the header may only **narrow** a manufacturer session |

The route code is identical in both cases — only the dependency changes. A
tenant-bound token asking for another customer is refused with **403 rather
than silently narrowed**: a client that asks to widen and receives a 200 has
been told it succeeded.

### The services, and which screen each one feeds

| Module | Feeds |
|---|---|
| `features.py` | the feature table everything else reads |
| `correlation.py` | Rule Studio step 3 |
| `rules_engine.py` | rule preview, deploy, versioning |
| `backtest.py` | the precision / coverage / lead-time cards |
| `scoring.py` | health index, probability, tiers, the cross-check sentence |
| `rul.py` | the degradation curve and projection |
| `cost.py` | every currency figure on every screen |
| `scoping.py` | the `Scope` object and its query helpers |
| `fleet_queries.py` | predictions, vehicles, parts, RUL read models |
| `insights.py` | Command Centre and Analytics aggregations |
| `workflow.py` | alerts and work orders, with audit logging |
| `llm.py` | the only module that imports `openai` |
| `agent_tools.py` | the assistant's 18 tools |

Business logic lives in `app/services/`, **never** in a route handler, so the
same functions could later be called from a scheduled job.

### The analytics, in one paragraph each

**Feature table.** One row per (vin, part_code, week): nine signals smoothed on
a 4-week rolling mean, `km_on_part`, `age_fraction`, and a binary
`failed_within_horizon`. The horizon is **90 days**, not 30 — at 30 days the
base failure rate is under 1% and any resulting probability is meaningless.
Only `event_type == 'failure'` is a label; counting preventive swaps would
teach the model that good maintenance is a fault.

**Correlation.** Signals ranked by **point-biserial correlation** — the correct
test for a continuous variable against a binary outcome — cross-checked against
standardised logistic regression coefficients, with both returned. Negative
correlations are floored at zero, because a negative weight would assert that a
signal protects against failure.

**Health index — one source of truth.**

```
health_index        = 100 − 70×age_fraction − 30×stress    (clamped 0–100)
failure_probability = 1 − health_index/100
```

Both the probability view and the RUL view derive from this single quantity,
which is *why* they can never contradict each other, and every detail response
carries a cross-check sentence naming the other view's numbers.

**Risk tiers.** GREEN < 0.40, AMBER 0.40–0.70, RED ≥ 0.70 — **and** anything
with 7 days or less of remaining life escalates to RED regardless of
probability, carrying an `escalated` flag and a written reason. Urgency is not
only a function of likelihood.

**Back-test.** Replays a rule over the trailing 12 months, deduplicating
consecutive alerts within 45 days into one episode. Fleet-wide: **precision
49%, coverage 88%, median warning 86 days** (41–72% precision per component).
All three sit inside the bands the spec expects. Right-censored episodes —
alerted, but the outcome is not yet observable — are excluded from precision
entirely, which is the standard treatment of a censored observation.

### The agent layer

The **Insight Agent** (`POST /api/chat`) runs a bounded tool loop: 18 tools, at
most `AGENT_MAX_TOOL_ROUNDS` (6) rounds. Every number in an answer must have
come back from a tool call, and citations are surfaced as chips. Hitting the
round limit is not an error — the model is asked to answer from what it
gathered and the response says `hit_round_limit`.

The **Action Agent** (`POST /api/chat/draft`) has **no tools at all**. It
receives a fixed fact sheet and writes a vendor or owner message from it, so it
cannot reach for data it was not given. That guarantee is structural rather than
requested.

Ask about a VIN that does not exist and it refuses rather than inventing one.

---

## API examples

Everything below goes through the frontend's origin, so it exercises the same
nginx proxy the app uses. Swap to `http://localhost:8000` to hit the API
directly.

### Health

```bash
curl -s http://localhost:5173/api/health
# {"status":"ok","app":"FleetGuard AI","environment":"development"}
```

### Sign in and use a token

```bash
TOKEN=$(curl -s -X POST http://localhost:5173/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"fleet@sarthilogistics.in","password":"fleetguard"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:5173/api/auth/me -H "Authorization: Bearer $TOKEN"
```

### Prove the tenant boundary

```bash
# their own fleet: 130 vehicles
curl -s "http://localhost:5173/api/vehicles?limit=1" \
  -H "Authorization: Bearer $TOKEN"

# asking to widen to every customer: 403, refused - not silently narrowed
curl -i -s "http://localhost:5173/api/vehicles?limit=1" \
  -H "Authorization: Bearer $TOKEN" -H "X-Customer-Scope: all"

# a rule deploy from a customer session: 403
curl -i -s -X POST http://localhost:5173/api/rules \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"part_code":"CLG-0311","signals":["high_rpm_dwell_time"]}'
```

### Without a token — the scope switcher's path

```bash
# the manufacturer view
curl -s "http://localhost:5173/api/overview" -H "X-Customer-Scope: all"

# one customer
curl -s "http://localhost:5173/api/overview" -H "X-Customer-Scope: 1"
```

### Predictions, one component on one truck

```bash
curl -s "http://localhost:5173/api/predictions?tier=RED&limit=5" \
  -H "X-Customer-Scope: all"

curl -s "http://localhost:5173/api/predictions/MZ4A110077/CLG-0311" \
  -H "X-Customer-Scope: all"
```

The detail response carries `failure_probability`, `health_index`, `risk_tier`,
the signal `drivers` behind the score, and the cross-check sentence tying it to
the RUL view.

### Preview and deploy a rule

`preview` writes nothing and is what Rule Studio calls on every signal toggle.
`signals: null` asks for the API's own suggested selection.

```bash
curl -s -X POST http://localhost:5173/api/rules/preview \
  -H "Content-Type: application/json" -H "X-Customer-Scope: all" \
  -d '{"part_code":"CLG-0311","signals":null}'

# deploying needs a manufacturer token
ADMIN=$(curl -s -X POST http://localhost:5173/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleetguard.ai","password":"fleetguard"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:5173/api/rules \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"part_code":"CLG-0311","signals":["high_rpm_dwell_time","dtc_recurrence_rate","harsh_braking_frequency","short_trip_ratio"]}'
```

**Deploying a rule does not rescore the fleet.** It writes a new active version
and retires the previous one; existing predictions keep the rule version they
were scored with until the next `python -m scripts.manage score`. Rule Studio
says so in the toast when you deploy.

### Ask the assistant

```bash
curl -s -X POST http://localhost:5173/api/chat \
  -H "Content-Type: application/json" -H "X-Customer-Scope: all" \
  -d '{"message":"Which component fails most often, and how many times?"}'
```

The response carries the answer, the tool calls it made, and the citations.

### Errors

Every error — including framework exceptions — comes back in one shape:

```json
{"error": "not_found", "message": "No vehicle X in this view.", "request_id": "..."}
```

422s add a `problems` array naming the offending field. **Branch on `error`,
never on the sentence.**

---

## Deployment

The compose file is the reference deployment: three services, one network, one
named volume for MySQL.

| Service | Image | Port | Notes |
|---|---|---|---|
| `mysql` | `mysql:8.0` | 3307 → 3306 | healthcheck pings `-h 127.0.0.1`, not `localhost` |
| `backend` | built from `fleetguard-backend/Dockerfile` | 8000 | migrates, then seeds and scores `--if-empty` |
| `frontend` | built from `fleetguard-frontend/Dockerfile` | 5173 → 80 | nginx serving the built SPA and proxying `/api` |

Three deployment details worth keeping if you adapt this:

- **The MySQL healthcheck must ping `-h 127.0.0.1`.** `localhost` uses a unix
  socket and answers while the server is still bootstrapping and not yet
  accepting TCP, so the backend starts too early and crash-loops.
- **Seeding without scoring gives you a fully populated database and empty
  screens.** The container command runs `score --if-empty` as well. That flag
  exists precisely because scoring takes about a minute and must not repeat on
  every restart.
- **The MySQL root password lives in the volume, not in the compose file.**
  Changing `MYSQL_ROOT_PASSWORD` on an existing volume does nothing; the volume
  keeps the password it was initialised with. `docker compose down -v` to start
  clean.

For anything beyond a POC: put the API behind a real reverse proxy with TLS,
set `AUTH_ENABLED=true`, replace the seeded demo users, move `JWT_SECRET` into a
secret store, and schedule `scripts.manage score` rather than running it by
hand.

---

## Decisions and resolved ambiguities

Recorded here as the spec requires.

**What does a rule output?** The spec renders a rule as
`failure_probability = 0.28 coolant_temp_variance + ...` in one section and as
`1 − health_index/100` in another. Both cannot be the definition. Resolved as:
the rule produces the **stress** term, and the health index combines that stress
with age to produce the probability the product displays and alerts on. The
back-test therefore replays the health-index probability at the RED threshold,
because that is what a customer would actually be paged by. Back-testing the raw
signal sum was measured and is strictly worse — 25% precision at 10% coverage,
because a brand-new part on a hard-driven truck alerts immediately.

**What is an alert episode?** An episode is an **interval** (first alert → last
alert of an unbroken run, where a gap over 45 days breaks the run), not a start
date. Both alternatives were measured and both are badly wrong: measuring from
the episode start splits one long warning into four alerts and destroys
precision; treating the episode as its start date alone pushes the only
matchable date months before the failure and takes coverage down to 38%.

**The Fleet screen has two modes.** The spec lists vehicle columns but the
component filter, sort keys and CSV export it also asks for are all
component-level. Both readings are real questions — "which trucks are at risk"
for a customer conversation, "which components do I schedule" for the workshop —
so the screen offers both over the same filters. By component is the default
because it is the unit of work.

**Cost exposure is drawn as a snapshot, never a time series.** The API scores
the fleet as it stands today; drawing exposure "over time" would mean inventing
history the product does not have. Exposure and avoidable are drawn **side by
side, not stacked**: exposure is probability-weighted across every component,
avoidable is the gross saving on the red ones. Different populations, so one is
not a share of the other.

**Two things measured and deliberately not done.** Censoring preventive swaps as
well as unresolved episodes takes precision to 99.9% — rejected, because it
hides the product's real limitation: when a part is age-dominated the alert
cannot distinguish "will fail" from "will be swapped on schedule anyway".
Rescaling the stress term gains 0.7pp of precision but pushes coverage to 91.4%,
outside the band the spec expects. **The data is not tuned to produce prettier
numbers.**

---

## Known limits

- **The data is synthetic.** The engine is validated — it recovers relationships
  it was never shown — but the specific signal-to-failure relationships are not
  claimed to hold on a real fleet. Real telematics is the next step.
- **`AUTH_ENABLED` is `false` by default**, so the scope switcher can be
  demonstrated without a login. Turning it on changes nothing a user can see; it
  only decides what happens when no token is presented, and it removes the
  one-click role cards from the sign-in screen.
- **Scoring is a batch step, not a live stream.** Predictions come from a
  scoring run rather than continuously from a telemetry feed.
- **The assistant runs on a free LLM tier** with an 8,000 token-per-minute
  ceiling — the same on every model available on the test account. Tool rounds
  request a smaller budget than answer rounds so two questions in a row both
  succeed. When the ceiling is hit the UI says so; it is a designed state, not a
  crash.

---

## Repository layout

```
fleetguard-backend/     FastAPI, SQLAlchemy, Alembic, the analytics engine
  app/routers/          thin HTTP layer, no business logic
  app/services/         all business logic, framework-free
  scripts/              generate_data, validate_recovery, manage CLI
  tests/                283 tests
fleetguard-frontend/    React 18 + Vite + TypeScript + Tailwind
  src/pages/            the seven screens
  src/components/ui/    the primitives - no UI kit, the identity is custom
  src/api/              one client, one error type, one scope header
docker-compose.yml      mysql + backend + frontend
```

## Tech stack

Python 3.11+ · FastAPI · SQLAlchemy 2.x · Pydantic v2 · MySQL 8 · Alembic ·
pandas / numpy / scipy / scikit-learn · Groq via the OpenAI-compatible SDK ·
React 18 · Vite · TypeScript · Tailwind · Recharts · Framer Motion ·
TanStack Query · React Router · Docker
