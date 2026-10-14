# Enterprise Financial Document Intelligence Platform

This repository contains a production-oriented foundation for a financial document intelligence SaaS platform that ingests invoices, credit notes, debit notes, R4C documents, settlement reports, GST documents, and related financial records.

## What This Initial Version Includes

- Modular backend skeleton (FastAPI)
- End-to-end pipeline contract (classification -> OCR/layout -> extraction -> validation -> normalization)
- Canonical normalized JSON schema with raw-preservation model
- Processing/job APIs to submit documents and track status
- Architecture and scale blueprint for enterprise deployment

## Planned Modules

1. Upload Engine
2. Document Processing Pipeline
3. OCR/Layout Engine
4. Classification Engine
5. Extraction and Line-Item Engine
6. Validation and Reconciliation Engine
7. Search and Analytics
8. Excel Export Engine
9. Enterprise Viewer
10. RBAC + Audit + Observability

## Quick Start

### 1) Create Python environment

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
```

### 2) Run API

```bash
uvicorn app.main:app --reload --app-dir backend
```

### 3) Open docs

Swagger: <http://127.0.0.1:8000/docs>

### 4) Run the UI

```bash
cd frontend
npm install
npm run dev
```

Open the app at <http://127.0.0.1:5173>. The UI proxies `/api` to the API on port 8000.

On Windows you can start both from the project root with `start.bat`.

Copy `.env.example` to `.env` and set `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. New uploads are stored in the private Supabase bucket `invoices` as well as the local `data/` folder. A machine with no local files (the ECS container) reads from Supabase.

## Deploy

### Frontend on Vercel

1. Import `https://github.com/devendrasingh123-b/invoice-Vr` in Vercel. Leave the root directory as the repository root (`vercel.json` builds `frontend/`).
2. After the API has a public URL, set `VITE_API_URL` to that URL (no trailing slash) and redeploy. Vercel bakes this in at build time.

### Backend on AWS ECS

Build the API image from the repo root:

```bash
docker build -t invoice-api:latest .
```

Push it to ECR, then run the Fargate task in `deploy/ecs-task-definition.json`. Set `SUPABASE_SECRET_KEY` in Secrets Manager. Do not put that key in the image or in git. The task listens on port 8000 and serves `GET /health`.

Put the load-balancer URL in Vercel as `VITE_API_URL`. Add that same site origin to `CORS_ORIGINS` if it is not a `*.vercel.app` address. `https://*.vercel.app` is already allowed.

## Repository Structure

```text
backend/
  app/
    main.py
    models.py
    pipeline.py
data/
  uploads/          # original uploaded files
  extractions/      # one normalized JSON file per document
  index.json        # lightweight document index
schemas/
  normalized-document.schema.json
docs/
  architecture.md
```

## Local JSON Storage

All extracted data is saved locally in this project as JSON only (no database).

- Each upload creates: `data/extractions/{job_id}.json`
- Document index: `data/index.json`
- Original files: `data/uploads/`

Each extraction JSON includes the full normalized document (header, vendor, line items, tax, validation, raw OCR text).

## Notes

- This baseline preserves all extracted/raw data by design.
- OCR and model providers are intentionally abstracted so you can plug in AWS Textract, Google Document AI, Azure Form Recognizer, Tesseract, PaddleOCR, or hybrid pipelines.
- The schema is designed to retain 100% source information while providing business-ready normalized output.
