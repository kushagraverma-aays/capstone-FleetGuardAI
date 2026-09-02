# FleetGuard AI — Databricks App

Self-contained deployment package for running FleetGuard AI as a
[Databricks App](https://docs.databricks.com/en/apps/index.html).

---

## Read this first if you are updating an existing deployment

Three things changed in the application code and they affect deployment
directly. If you replace an older copy of this folder, do not carry the old
`app.yaml` or `requirements.txt` forward.

**1. TLS to MySQL is now a setting, not hardcoded.** `app/db.py` and
`alembic/env.py` used to carry `connect_args={"ssl": {...}}` inline. They now
read `settings.db_connect_args`, which is driven by `MYSQL_SSL`. That keeps one
codebase working against both a local MySQL and Azure Database for MySQL
Flexible Server, which runs with `require_secure_transport` ON and refuses an
unencrypted connection.

> **`MYSQL_SSL=true` must be set for the deployed app.** It is already in the
> `app.yaml` in this folder. Leave it out and the app starts but cannot reach
> the database — `/api/health/ready` reports `database: unreachable` and every
> screen is empty. The same applies to any local shell you point at the hosted
> database to run migrations.

**2. passlib is gone from `requirements.txt`.** It read
`bcrypt.__about__.__version__` at import time to detect its backend, and that
attribute was removed in bcrypt 4.1, so an unpinned install of the two together
fails. `app/security.py` calls bcrypt directly instead. Existing password
hashes are unaffected — they are ordinary bcrypt hashes either way, so the
seeded logins keep working without a re-seed.

**3. An unmatched `/api/...` path returns a real JSON 404.** The SPA catch-all
in `app/main.py` matches every path, including API paths that no router
claimed. Previously those answered `200` with `index.html`, and the frontend —
which parses one error envelope for the whole product — reported that as a JSON
parse failure rather than as a missing endpoint.

---

## Where the code comes from

`fleetguard-backend/` is the single source of truth. The `app/`, `alembic/`,
`scripts/` and `tests/` directories in this folder are a **snapshot** of it, so
that this one folder can be uploaded on its own.

- `.github/workflows/deploy.yml` refreshes that snapshot from
  `fleetguard-backend/` on every push to `main`, rebuilds the frontend, and
  deploys. Nothing needs to be copied by hand for that path.
- If you deploy by hand, re-copy `app/` and `scripts/` from
  `fleetguard-backend/` first, or you will ship whatever was committed last.

Never edit `fleetguard-databricks-app/app/` directly. The next push overwrites
it.

---

## What You Upload

**Upload ONLY this `fleetguard-databricks-app/` folder.** It already contains:

| Contents | Description |
|----------|-------------|
| `app/` | Complete FastAPI backend (routers, services, models, auth, etc.) |
| `alembic/` | Database migrations |
| `data/` | Seed data (planted_weights.json) |
| `scripts/` | Data generation + build scripts |
| `tests/` | Test suite (not run by the app; here so the folder stands alone) |
| `static/` | Built React frontend |
| `run.py` | Entry point — binds the port Databricks provides |
| `app.yaml` | Databricks App manifest |
| `requirements.txt` | All Python dependencies |

You do **NOT** upload `fleetguard-backend/` or `fleetguard-frontend/` separately.

---

## What You Need to Install / Configure in Databricks

### Pre-requisites (BEFORE deploying)

| Requirement | Why | How |
|-------------|-----|-----|
| **MySQL database** | App stores all data here | Use **Azure Database for MySQL**, **AWS RDS**, or any MySQL 8.x accessible from Databricks. Note the host, port, user, password. |
| **Node.js ≥ 18** (local only) | To build the React frontend | Install from [nodejs.org](https://nodejs.org/) on your local machine |
| **Databricks CLI** | To deploy the app | `pip install databricks-cli` then `databricks configure` |

### No additional Databricks resources needed
- ❌ No cluster needed — Databricks Apps run as serverless containers
- ❌ No Spark — the app is pure Python (FastAPI + scikit-learn)
- ❌ No Unity Catalog — data lives in MySQL
- ✅ Just the **Databricks App runtime** (included in your workspace)

---

## Step-by-Step Deployment

### Step 1: Build the frontend (on your local machine)

```powershell
# Windows
cd fleetguard-databricks-app
.\scripts\build_and_prepare.ps1
```

```bash
# Linux / Mac
cd fleetguard-databricks-app
chmod +x scripts/build_and_prepare.sh
./scripts/build_and_prepare.sh
```

This builds `fleetguard-frontend/` and replaces `static/` with the build
output. The bundle committed here is already current, so this is only needed
after a frontend change.

### Step 2: Create `.env` file (for local testing, optional)

```bash
cp .env.example .env
# Edit .env with your MySQL credentials, and set MYSQL_SSL=true if that
# database is a managed one.
```

### Step 3: Configure `app.yaml` (for Databricks)

The `app.yaml` here is filled in and working. Change these if the database or
the workspace is not the same one:

```yaml
env:
  - name: MYSQL_HOST
    value: "your-mysql-host.mysql.database.azure.com"   # CHANGE
  - name: MYSQL_USER
    value: "fleetguard_user"                            # CHANGE
  - name: MYSQL_DB
    value: "fleetguard"
  - name: MYSQL_SSL
    value: "true"                                       # required for Azure MySQL
  - name: MYSQL_PASSWORD
    valueFrom: "mysql_pswd"                             # Databricks secret
  - name: JWT_SECRET
    valueFrom: "jwt_secret"                             # Databricks secret
  - name: LLM_API_KEY
    valueFrom: "api_key"                                # Databricks secret (Groq)
```

The three secrets are Databricks secret resources referenced by name. Set them
on the app under **Compute → Apps → fleetguard-ai → Configure**, not in this
file.

Without `LLM_API_KEY` the app still runs: `/api/health/ready` reports the model
as `not_configured` and the assistant panel says so, while every other screen
works normally.

### Step 4: Deploy to Databricks

**Option A: From Databricks Dashboard (UI)**
1. Go to your Databricks workspace → **Apps**
2. Click **Create App**
3. Upload the entire `fleetguard-databricks-app/` folder
4. Set the environment variables in the app configuration
5. Click **Deploy**

**Option B: From CLI**
```bash
# First time
databricks apps create fleetguard-ai --source-code-path ./fleetguard-databricks-app

# Update existing app
databricks apps deploy fleetguard-ai --source-code-path ./fleetguard-databricks-app
```

**Option C: automatically, on push to `main`** — `.github/workflows/deploy.yml`
does Option B for you. It needs the repository secrets `DATABRICKS_HOST` and
`DATABRICKS_TOKEN`, and the workspace path inside it must belong to the user
that token authenticates as.

### Step 5: Initialize the database

The app runs one process — uvicorn — and does **not** migrate or seed on
startup. Do this once, from your own machine, pointed at the same database the
app uses:

```bash
cd fleetguard-backend

# .env must carry the hosted database's host/user/password AND:
#   MYSQL_SSL=true
python -m scripts.manage rebuild
```

`rebuild` runs init-db, seed, score and validate in order. The individual
commands (`init-db`, `seed`, `score`, `validate`) are all idempotent and safe
to re-run if you would rather do them one at a time.

### Step 6: Verify

Open the app URL provided by Databricks. You should see:
- ✅ Dashboard with KPI cards
- ✅ All navigation working
- ✅ API docs at `/docs`
- ✅ Health check at `/api/health`
- ✅ `/api/health/ready` reporting `database: ok` — this is the one that proves
  `MYSQL_SSL` and the credentials are right

---

## Architecture

```
Browser → Databricks App (DATABRICKS_APP_PORT)
           │
           ├── /api/*        → FastAPI (fleet, insights, rules, chat, auth, etc.)
           ├── /docs         → Swagger UI
           ├── /assets/*     → Bundled JS/CSS (Vite output)
           └── /*            → index.html (React Router handles SPA routes)
```

One process serves both, so the browser never makes a cross-origin request and
there is no API base URL to configure. `app/main.py` mounts `static/` only when
`static/index.html` exists — which is why a plain `fleetguard-backend/` checkout
keeps letting the Vite dev server own the UI.

---

## Directory Structure

```
fleetguard-databricks-app/
├── app.yaml                          # Databricks App manifest
├── run.py                            # Entry point (reads DATABRICKS_APP_PORT)
├── requirements.txt                  # Python deps (installed by Databricks)
├── .env.example                      # Template for local .env file
├── alembic.ini                       # Alembic migration config
├── alembic/                          # Database migrations
│   ├── env.py
│   └── versions/
├── app/                              # FastAPI application
│   ├── main.py                       # App factory, middleware, SPA serving
│   ├── config.py                     # Pydantic Settings
│   ├── db.py                         # SQLAlchemy engine
│   ├── models.py                     # ORM models
│   ├── constants.py                  # Application constants
│   ├── deps.py                       # FastAPI dependencies
│   ├── security.py                   # bcrypt hashing, JWT issue/decode
│   ├── rate_limit.py                 # Rate limiting
│   ├── logging_config.py             # Structured logging
│   ├── schemas/                      # Pydantic response schemas
│   ├── routers/                      # API route handlers
│   │   ├── auth.py                   # Login / token / demo accounts
│   │   ├── fleet.py                  # Vehicles, predictions, RUL
│   │   ├── insights.py               # Dashboard overview
│   │   ├── rules.py                  # Rules engine, history, restore
│   │   ├── workflow.py               # Workflow management
│   │   ├── export.py                 # Data export
│   │   └── chat.py                   # AI chatbot
│   └── services/                     # Business logic
├── data/                             # Seed data
├── scripts/                          # CLI tools + build scripts
├── static/                           # Built React frontend
└── tests/                            # Test suite
```

## Updating After Code Changes

```bash
# Backend changed  → re-copy app/ and scripts/ from fleetguard-backend/
# Frontend changed → re-run scripts/build_and_prepare.ps1 (or .sh)
# Then re-deploy:
databricks apps deploy fleetguard-ai --source-code-path ./fleetguard-databricks-app
```

Or just push to `main` and let the workflow do all three.
