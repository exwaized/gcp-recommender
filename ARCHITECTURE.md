# Recommender Blueprint — Architecture Walkthrough

A systematic tour of the data model, ML pipeline, API surface, and monitoring
stack in this repo — and the engineering calls behind each layer, including
the ones made under a "no billing account" constraint.

> Generated from a direct read of the repository — every claim below traces
> to a specific file. Re-run this walkthrough after any change to `api/`,
> `models/`, or `data/` to keep it honest.

---

## 1. Overview — the core tension

This is a collaborative-filtering recommender whose code is written against
GCP primitives — BigQuery-shaped tables, a Vertex AI prediction contract,
Cloud Logging-shaped output — but whose only real deployment runs on Oracle
Cloud's Always Free tier. GCP was never provisioned; it didn't need to be,
because the codebase treats "which cloud" as a configuration detail rather
than a foundation.

Every layer is built around one seam: swap the concrete backend, keep the
interface. That seam is what let the project go from a laptop with SQLite,
to a real hosted Oracle Autonomous Database and a public compute instance,
without touching `api/` or `models/`.

**Why Oracle, not GCP.** Oracle Cloud's Always Free tier includes an
Autonomous Database and an ARM compute instance with no time limit and no
card-triggered charges. Cloud Run, BigQuery, and Vertex AI have free tiers
too, but provisioning any of them still requires a billing-enabled GCP
project. The architecture stayed GCP-shaped; the deployment target moved to
whichever free tier didn't require one.

---

## 2. Architecture — four layers, one swap point each

Data, model, serving, and observability are each written against a small
interface. `●` = running today, `┄` = the GCP service each layer was
drafted against but never provisioned.

```
 DATA LAYER          MODEL LAYER            SERVING LAYER         OBSERVABILITY
 ───────────         ───────────            ─────────────         ─────────────
 Warehouse       →   ALS + MLflow       →   FastAPI            →  JSON → stdout
 ● sqlite /          ● numpy ALS,           ● docker on            ● structured
   oracle adb           local mlruns/          oracle vm              logger
 ┄ bigquery          ┄ vertex ai            ┄ cloud run         ┄ cloud logging
   (drafted)            registry (drafted)     (drafted)           (drafted)
```

Swap mechanism: one env var per seam — `WAREHOUSE_BACKEND=oracle` is the
only line that changes between a laptop run and the live deployment.

### The swap table

| Local (default) | Oracle Cloud (deployed) | GCP equivalent (drafted, not provisioned) |
|---|---|---|
| SQLite — `warehouse.db` | Oracle Autonomous DB, via `oracle_warehouse.py` | BigQuery |
| MLflow, local file store | same store, on the compute instance | Vertex AI Model Registry |
| uvicorn, reload on | Docker on a `VM.Standard.A1.Flex` | Cloud Run |
| JSON logs → stdout | same, no sink attached | Cloud Logging |
| SQLite metrics table | unchanged, on-instance | Cloud Monitoring |

---

## 3. Data model — three tables, no declared foreign keys

The warehouse holds `users`, `items`, and `interactions` — an event table
joined against two dimension tables, shaped to read the same whether it's a
2 MB SQLite file or a real Autonomous Database.

```
 users                    interactions                   items
 ─────────────            ─────────────────────          ─────────────
 user_id       PK         interaction_id     PK           item_id      PK
 age_group     ┄────────  user_id  → users                title
 city                     item_id  → items  ────────┄     category
 signup_date               event_type                      brand
 segment                   rating                          price
                            timestamp                       avg_rating

                  no FK constraint enforced in either DDL
```

### How the synthetic dataset is shaped

`data/generate_data.py` produces 500 users, 200 items, and 15,000
interactions — but not uniformly at random. Each user is assigned 2–4
preferred categories up front, and category sampling is weighted 5:1 toward
those preferences, so the resulting matrix has the kind of structure a real
ALS model can actually learn from, rather than pure noise.

- **Event mix** is drawn from a fixed pool —
  `["view","view","view","add_to_cart","purchase"]` — giving roughly 60%
  views, 20% cart-adds, 20% purchases.
- **Ratings** only exist on purchase events, sampled from a Gaussian
  (μ=4.0, σ=0.8) and clipped to [1, 5].
- **No table has a declared foreign key** in either the SQLite or Oracle
  DDL — `interactions.user_id` / `item_id` are logical references only,
  kept consistent by construction rather than by constraint.

---

## 4. Pipeline workflow — generate → train → register → serve

`run_pipeline.py` runs all three stages in order and smoke-tests the API —
a one-file stand-in for what would otherwise be a Cloud Composer DAG or a
Vertex AI Pipeline.

1. **Generate & load** — `generate_data.py` builds the three DataFrames and
   calls `load_to_warehouse()`, which drops/recreates tables and
   bulk-inserts — a full replace, not an incremental load.
2. **Build the interaction matrix** — `train.py` pulls `interactions` via
   `query_warehouse()`, maps `event_type` to a weight (purchase=5.0,
   add_to_cart=2.0, view=0.5), and assembles a sparse `users × items` CSR
   matrix.
3. **Train ALS** — 10 iterations of alternating least squares, implemented
   directly in NumPy — no `implicit`, no GPU. Each pass logs an MSE-style
   loss under an MLflow run.
4. **Save & register** — factors are written as `.npy` + a `meta.json`
   index (no pickle). `model_registry.json` is overwritten with the run
   id, coverage metric, and a `"PRODUCTION"` status — a one-row registry,
   not a versioned one.
5. **Serve** — FastAPI's `lifespan` hook loads the saved model once at
   process startup. If `saved_model/` doesn't exist, the API still starts —
   `/health` reports `"degraded"` and prediction routes return `503`
   instead of crashing the process.

---

## 5. Model internals — implicit ALS, written by hand

`CollaborativeFilteringModel` implements the Hu/Koren/Volinsky
implicit-feedback formulation directly: confidence comes from the event
weight, and the model fits toward a binary preference signal (interacted vs.
not), not the raw weight itself.

```
A = Yᵀ · C_u · Y + λI          # normal equations per user row
b = Yᵀ · (C_u · p_u)           # p_u is binary: 1 where weight > 0
x_u = solve(A, b)              # np.linalg.solve, not a matrix inverse
```

Both the user-factor and item-factor passes solve this per-row, alternating
for 10 iterations, seeded with a fixed `np.random.default_rng(42)` so
training is reproducible run to run.

**Cold start.** A `user_id` absent from `user_index` — anyone who signed up
after the last training run — falls back to `_popular_fallback()`: items
sorted by `avg_rating`, with `score: 0.0` so the response shape stays
identical whether the ranking came from the model or from a fallback.

**Item similarity, precisely.** `similar_items()` takes the raw dot product
of item-factor vectors, not a normalized cosine similarity — factor vectors
aren't unit-normalized before the dot product, so items with
large-magnitude factors (i.e. more total interaction weight) can rank ahead
of a genuinely closer but less-popular item. The README's "cosine
similarity" description is the intent, not quite what the code does.

**Where this doesn't scale.** Training densifies the sparse matrix
(`matrix.toarray()`) and rebuilds a full `n_items × n_items` diagonal
confidence matrix per user, per iteration. At 500 users × 200 items that's
instant; at BigQuery-scale interaction volume it would need the sparse
formulation the `implicit` library already provides.

---

## 6. API reference — nine routes, one process

FastAPI serves both the prediction endpoints and the raw warehouse reads
(the BigQuery-console equivalent) from the same app. A single ASGI
middleware logs every request's method, path, status, and latency through
the structured logger.

| Route | Purpose |
|---|---|
| `GET /health` | Model-loaded state, warehouse backend, UTC timestamp — the readiness probe. |
| `GET /model/info` | Dumps `model_registry.json` as-is. |
| `POST /recommend` | `{user_id, n, exclude_seen}` → top-N ranked items with scores. |
| `POST /similar-items` | `{item_id, n}` → nearest items by factor dot product. |
| `POST /predict` | Vertex AI batch contract — `{instances: [{user_id, n}, ...]}` → `{predictions: [...]}`. |
| `GET /users` | Paginated user list (`limit`/`offset`) with a total count. |
| `GET /users/{id}` | One user's profile joined against their last 20 interactions. |
| `GET /items` | Item catalog, optionally filtered by `category`. |
| `GET /analytics/summary` | Row counts plus top-5 categories and event-type breakdown — small aggregate queries run on demand, not materialized. |
| `GET /metrics` | Cloud Monitoring-equivalent read path — a rollup of `request_latency_ms` plus the last 200 raw samples. |

**The `/predict` contract exists on purpose.** Nothing calls it as a Vertex
AI endpoint today — but shaping it identically to Vertex AI's
`instances`/`predictions` format means the serving layer could sit behind
Vertex AI Prediction later with zero client-facing change.

---

## 7. Monitoring & observability — both pieces wired in

Two components exist under `monitoring/`. Both are on the request path.

**`StructuredLogger`.** Every log line is a single JSON object written to
stdout: `timestamp`, `severity`, `component`, `event`, plus whatever
keyword fields the call site adds. The API's request middleware calls it on
every response with `latency_ms`; startup, shutdown, and each `/recommend`
call log through it too. This shape is deliberately what Cloud Logging's
stdout agent auto-parses — the comment in the file says the swap is
`google.cloud.logging.Client().setup_logging()`, and nothing else would
need to change.

**`MetricsCollector`.** A SQLite-backed counter/latency store
(`monitoring/metrics.db`) with `.record()` and `.get_summary()`, shaped
after Cloud Monitoring's custom-metric API. The same request middleware now
calls `metrics.record("request_latency_ms", ...)` on every response, and
`GET /metrics` exposes a rollup plus the last 200 raw samples — see
[Known gaps](#10-known-gaps--whats-incidental-not-deliberate) for the
retention caveat that comes with it.

---

## 8. Deployment — serve-only image, trained out-of-band

The Docker image never trains a model — it can't. Real Oracle credentials
don't exist at build time, so training happens on the instance, against the
live warehouse, before or after the container starts.

```bash
docker build -t gcp-recommender .
docker run -d -p 8080:8080 --env-file .env \
  -e WAREHOUSE_BACKEND=oracle \
  -v $(pwd)/models/saved_model:/app/models/saved_model \
  gcp-recommender
```

The saved model is mounted as a volume rather than baked into the image, so
retraining doesn't require a rebuild — swap the directory contents and
restart the container. `scripts/cloud-init.yaml` provisions the compute
instance itself: installs Docker, enables it at boot, and opens port 8080
in the instance's own iptables rules (OCI's security-list allow rule alone
isn't enough — the guest firewall blocks it too, a detail that's easy to
lose an afternoon to).

---

## 9. Engineering decisions

Eight calls that shaped the codebase, in the order you'd hit them reading
top to bottom. Each is inferred from what the code actually does and the
comments left in it — not from anyone's stated intent.

### D1 — One dispatcher module for the warehouse, not per-caller branching

**Decision.** `data/warehouse.py` is the only place that reads
`WAREHOUSE_BACKEND`. Everything in `api/` and `models/` imports
`query_warehouse` from there, never from `generate_data.py` or
`oracle_warehouse.py` directly.

**Why.** A single seam means the SQLite→Oracle swap — and a future
Oracle→BigQuery swap — is one environment variable, not a search-and-replace
across every caller.

### D2 — SQLite schema mirrors the BigQuery/Oracle table shapes exactly

**Decision.** Column names and types in `generate_data.py`'s `SCHEMA` match
`oracle_warehouse.py`'s field-for-field, down to using the same SQL in
`query_warehouse` calls throughout the codebase.

**Why.** Every query written and tested locally against SQLite runs
unmodified against the real warehouse — the schema mirroring is what makes
the dispatcher in D1 actually swappable rather than swappable-in-theory.

### D3 — Oracle Always Free as the real deployment target

**Decision.** The live deployment is Oracle Cloud, not GCP — a real
Autonomous Database and a real compute instance, provisioned by
`scripts/oci_provision.sh`.

**Why.** Oracle's Always Free tier needs no billing-enabled account. GCP's
free tiers do. The codebase stays GCP-shaped so the swap back is still just
a config change, not a rewrite, whenever that constraint lifts.

### D4 — Hand-rolled ALS instead of the `implicit` library

**Decision.** Training is plain NumPy — dense matrices,
`np.linalg.solve` per row — rather than a call into `implicit`'s
Cython/BLAS-backed ALS.

**Why (inferred).** `requirements.txt` has no `implicit` dependency, and
the target compute shape is an ARM `VM.Standard.A1.Flex` instance — a
platform where a compiled Cython extension is more likely to need a source
build than find a prebuilt wheel. Pure NumPy trades training-loop speed for
a dependency that installs the same way everywhere. It's the right trade at
500 users × 200 items and the wrong one past it — see
[Model internals](#5-model-internals--implicit-als-written-by-hand).

### D5 — Model persistence: `.npy` + JSON, explicitly not pickle

**Decision.** `save()`/`load()` write factor arrays as `.npy` and
everything else as a plain `meta.json`. The docstring says so directly:
"no pickle, no joblib."

**Why.** A pickled model executes arbitrary code on load and breaks across
Python/library versions in ways that are painful to debug on a remote
instance. Numpy arrays and JSON have neither problem — the trade is writing
`save`/`load` by hand instead of getting them for free.

### D6 — MLflow, but pointed at a local file store

**Decision.** `mlflow.set_tracking_uri()` points at `models/mlruns/` on
disk — no tracking server, no managed backend.

**Why.** Runs, params, and metrics are still tracked with the real MLflow
API, so pointing the same URI at a hosted server or Vertex AI's MLflow
integration later is a one-line change — without standing up tracking
infrastructure for a single-node deployment that doesn't need it yet.

### D7 — Structured JSON to stdout, not plain-text logs

**Decision.** `StructuredLogger` emits one JSON object per line to stdout
instead of a formatted string.

**Why.** Cloud Logging's stdout agent parses JSON lines automatically —
this format is what makes the Cloud Logging swap in D3's table a config
change rather than a logging rewrite, and it's still perfectly readable
with `docker logs` in the meantime.

### D8 — No foreign keys in either warehouse schema

**Decision.** Neither the SQLite nor the Oracle DDL declares a foreign key
from `interactions` to `users`/`items`.

**Why (inferred).** Both loaders do a full replace —
`to_sql(if_exists="replace")` locally, `DELETE` + bulk `executemany` on
Oracle. FK constraints would force load order and add rollback handling
neither loader has; referential integrity is kept by construction
(interactions are generated from the same in-memory user/item frames)
instead of by the database.

### D9 — CORS defaults open, but is now a config knob, not a hardcode

**Decision.** `api/main.py` reads `CORS_ALLOW_ORIGINS` (comma-separated) and
falls back to `*` only when it's unset.

**Why.** The documented way to use this API is the React dashboard opened
as a claude.ai-hosted artifact (`dashboard/Dashboard.jsx`, pointed at
`http://localhost:8080`) — that's a cross-origin call from an origin that
isn't known in advance, which is what an open default was working around.
Making it a config knob keeps that flow working out of the box while
giving any real deployment a one-line way to lock it down, e.g.
`CORS_ALLOW_ORIGINS=https://claude.ai,http://localhost:5173` — the same
env-var-swap idiom as D1's warehouse backend.

---

## 10. Known gaps — what's incidental, not deliberate

Not everything above is a decision — some of it is just what's true right
now. Worth knowing before treating any of it as settled.

### Resolved

These five were flagged in an earlier pass of this document and have since
been fixed in the code:

- **Metrics collector wasn't called anywhere** → `MetricsCollector` is now
  instantiated in `api/main.py` and recorded to from the request-logging
  middleware; `GET /metrics` exposes it. See
  [Monitoring & observability](#7-monitoring--observability--both-pieces-wired-in).
- **Two copies of the same model class** → `models/collaborative_filtering.py`
  was dead code (nothing imported it) and has been deleted. `train.py`'s
  inline `CollaborativeFilteringModel` remains the one real implementation.
- **"Cosine similarity" was a raw dot product** → `similar_items()` now
  divides by the norm of both vectors before ranking, so scores are a true
  bounded cosine similarity instead of scaling with each item's total
  interaction weight. See
  [Model internals](#5-model-internals--implicit-als-written-by-hand).
- **CORS was hardcoded wide open** → it's now a config knob defaulting to
  open, for the reason the dashboard needs it. See
  [D9](#d9--cors-defaults-open-but-is-now-a-config-knob-not-a-hardcode).
- **The model registry had no version history** → `train_and_register()`
  now archives the outgoing entry into a `history` array on every run
  instead of overwriting it. `/model/info`'s top-level shape is unchanged,
  so nothing that reads it needed to change.

### Still true

- **`model_registry.json` stores an absolute path.** `artifact_path` is
  still written as a literal path from wherever training last ran — not
  fixed here, since nothing in the codebase treats it as more than
  informational (`load_model()` reconstructs the path itself rather than
  reading this field).
- **Neither the metrics table nor the registry history prunes itself.**
  `monitoring/metrics.db` grows by one row per request forever, and every
  training run appends to `model_registry.json`'s `history` array with no
  cap. Both are fine at demo scale — training happens on demand, not on a
  schedule, and `get_summary()`/`get_all_metrics()` already cap what they
  *read* back — but a long-running deployment would eventually want a
  retention policy on both.
