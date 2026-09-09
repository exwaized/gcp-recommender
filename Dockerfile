FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Serve only — the model is trained separately (scripts/seed_warehouse.py +
# models/train.py) against the real warehouse backend and either baked into
# the image via `models/saved_model/` or mounted in at `docker run` time.
# Real DB credentials aren't available at build time, so training does not
# happen here (see README > Oracle Cloud deployment).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
