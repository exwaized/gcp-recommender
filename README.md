# GCP Recommendation Engine

End-to-end collaborative filtering recommender — architected for Google Cloud Platform, runnable locally without any GCP account or billing.

## Architecture

```
Data Layer          Model Layer           Serving Layer         Observability
─────────────       ─────────────         ─────────────         ─────────────
SQLite              ALS Matrix            FastAPI               Structured JSON
(BigQuery swap)  →  Factorization      →  (Cloud Run swap)   +  Logging
                    MLflow Registry                             (Cloud Logging swap)
                    (Vertex AI swap)      /recommend
                                          /similar-items
                                          /predict  ← Vertex AI contract
```

## Quickstart

```bash
# Install
pip install -r requirements.txt

# Run everything
python run_pipeline.py

# Or step by step:
python data/generate_data.py    # Generate 500 users, 200 items, 15K interactions
python models/train.py          # Train ALS, register to MLflow
uvicorn api.main:app --port 8080  # Serve predictions
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service health check |
| `/recommend` | POST | Top-N recs for a user |
| `/similar-items` | POST | Item-to-item similarity |
| `/predict` | POST | Vertex AI-compatible batch prediction |
| `/analytics/summary` | GET | Dataset statistics |
| `/metrics` | GET | Request latency rollup + recent samples (Cloud Monitoring-equivalent) |
| `/model/info` | GET | MLflow registry entry |
| `/docs` | GET | Auto-generated Swagger UI |

## Cloud Production Swap Guide

The original design targeted GCP (BigQuery / Vertex AI / Cloud Run). The actual
live deployment runs on **Oracle Cloud's Always-Free tier** instead, since it
doesn't require a billing account — but the swap points are the same idea:

| Local component | Oracle Cloud (implemented) | GCP equivalent (not deployed) |
|----------------|------------------------------|--------------------------------|
| SQLite (`warehouse.db`) | Oracle Autonomous Database — `data/oracle_warehouse.py`, toggled via `WAREHOUSE_BACKEND=oracle` | BigQuery |
| MLflow registry | Same MLflow local file store, on the compute instance | Vertex AI Model Registry |
| uvicorn FastAPI | Docker container on a `VM.Standard.A1.Flex` Always-Free instance | Cloud Run |
| Structured JSON logs | stdout, same format (no managed sink wired up) | Cloud Logging |
| Local metrics DB | unchanged (SQLite, on-instance) | Cloud Monitoring |

### Oracle Cloud deployment

1. **Sign up** at [cloud.oracle.com/free](https://cloud.oracle.com/free) (Always Free tier — no time limit, no charge unless you upgrade).
2. **Set up the CLI**: generate an API signing key (Console → Profile → User Settings → API Keys), install the OCI CLI, then run `oci setup config`.
3. **Provision resources**: edit the variables at the top of `scripts/oci_provision.sh` (compartment OCID, region, SSH key, DB admin password), then run it. It creates a VCN/subnet/security list, an Always-Free Autonomous Database (DW workload), and an Always-Free `VM.Standard.A1.Flex` compute instance (4 OCPU / 24GB, Ubuntu, Docker pre-installed via cloud-init).
4. **Get DB connection info**: in the console, open the Autonomous Database → DB Connection → TLS tab (not the wallet/mTLS tab) and copy the connect descriptor into `ORACLE_CONNECT_STRING`. Copy `.env.example` to `.env` and fill in `ORACLE_USER` / `ORACLE_PASSWORD` / `ORACLE_CONNECT_STRING`.
5. **Ship the code to the instance** (`scp`/`rsync` the repo, or `git clone` if pushed to a remote), then on the VM:
   ```bash
   pip install -r requirements.txt   # or run these two steps in a venv
   WAREHOUSE_BACKEND=oracle python scripts/seed_warehouse.py   # loads synthetic data into ADB
   WAREHOUSE_BACKEND=oracle python models/train.py             # trains ALS against real ADB data
   docker build -t gcp-recommender .
   docker run -d -p 8080:8080 --env-file .env -e WAREHOUSE_BACKEND=oracle \
     -v $(pwd)/models/saved_model:/app/models/saved_model gcp-recommender
   ```
6. **Verify**: `curl http://<instance-public-ip>:8080/health` should report `"warehouse_backend": "oracle"`.

## Model Details

- **Algorithm**: Implicit ALS (Alternating Least Squares) matrix factorization
- **Signal weighting**: purchase=5.0, add_to_cart=2.0, view=0.5
- **Cold-start handling**: popularity fallback for unseen users
- **Item similarity**: cosine similarity in latent factor space
- **Prediction contract**: matches Vertex AI `/predict` endpoint schema

## Project Structure

```
gcp-recommender/
├── data/
│   └── generate_data.py     # Synthetic dataset + BigQuery-schema SQLite
├── models/
│   └── train.py             # ALS training + MLflow registry
├── api/
│   └── main.py              # FastAPI server (Cloud Run ready)
├── monitoring/
│   ├── logger.py            # Structured JSON logging (Cloud Logging compatible)
│   └── metrics.py           # Metrics collector (Cloud Monitoring compatible)
├── dashboard/
│   └── Dashboard.jsx        # React live demo dashboard
├── Dockerfile               # Cloud Run deployment
├── requirements.txt
└── run_pipeline.py          # One-command orchestration
```
