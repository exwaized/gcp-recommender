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
| `/model/info` | GET | MLflow registry entry |
| `/docs` | GET | Auto-generated Swagger UI |

## GCP Production Swap Guide

| Local component | GCP equivalent | Swap |
|----------------|----------------|------|
| SQLite (`warehouse.db`) | BigQuery | Replace `query_warehouse()` with `bigquery.Client().query().to_dataframe()` |
| MLflow registry | Vertex AI Model Registry | Replace `mlflow.log_artifact()` with `aiplatform.Model.upload()` |
| uvicorn FastAPI | Cloud Run | `gcloud run deploy` from Dockerfile |
| Structured JSON logs | Cloud Logging | `google.cloud.logging.Client().setup_logging()` |
| Local metrics DB | Cloud Monitoring | `monitoring_v3.MetricServiceClient` |

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
