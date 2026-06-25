# ticket-sorter

A small FastAPI service that classifies customer support tickets for a digital
finance company (think bKash / Nagad / mobile-money wallets). Each incoming
message is routed to the right team — customer support, dispute resolution,
payments ops, or fraud risk — using pure Python keyword rules.

**No LLM. No API key. No external calls.** Just if/elif/else on the message
text, so the demo runs offline.

## Endpoints

| Method | Path           | Purpose                                          |
| ------ | -------------- | ------------------------------------------------ |
| GET    | `/health`      | Liveness probe (`{"status":"ok", ...}`)         |
| POST   | `/sort-ticket` | Classify a customer message and return routing   |
| GET    | `/docs`        | Auto-generated Swagger UI                       |

### `POST /sort-ticket`

Request body:

```json
{
  "ticket_id": "T-001",
  "message": "I sent 5000 taka to a wrong number"
}
```

Response:

```json
{
  "ticket_id": "T-001",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports sending money to the wrong number/account and is requesting recovery of the transferred amount.",
  "human_review_required": true,
  "confidence": 0.85
}
```

`human_review_required` is `true` when `severity = "critical"` or
`case_type = "phishing_or_social_engineering"`.

## How classification works

The classifier lowercases the message and runs it through an ordered if/elif
chain over keyword lists — phishing first (highest-stakes misroute), then
wrong-transfer, then payment-failed, then refund, then `other` as the catch-all.

Once the `case_type` is chosen, `severity` and `department` are looked up
from the spec's fixed tables.

### Case type keywords (priority order)

1. **phishing_or_social_engineering** — `otp`, `pin`, `share my pin`,
   `asked for my otp`, `click the link`, `phishing`, `scam link`, `fraud call`, …
2. **wrong_transfer** — `wrong number`, `sent to wrong`, `by mistake`,
   `accidentally sent`, `wrong transfer`, `recover my money`, …
3. **payment_failed** — `payment failed`, `transaction failed`, `declined`,
   `money deducted`, `did not receive`, `cash out failed`, …
4. **refund_request** — `refund`, `money back`, `overcharged`, `double charged`,
   `unauthorized charge`, `cancel transaction`, …
5. **other** — none of the above.

### Severity mapping (deterministic)

| Case type                        | Severity   |
| -------------------------------- | ---------- |
| `wrong_transfer`                 | `high`     |
| `payment_failed`                 | `high`     |
| `phishing_or_social_engineering` | `critical` |
| `refund_request`                 | `low`      |
| `other`                          | `low`      |

### Department mapping (deterministic)

| Case type                        | Department           |
| -------------------------------- | -------------------- |
| `wrong_transfer`                 | `dispute_resolution` |
| `payment_failed`                 | `payments_ops`       |
| `phishing_or_social_engineering` | `fraud_risk`         |
| `refund_request`                 | `customer_support`   |
| `other`                          | `customer_support`   |

### Human review rule

`human_review_required = severity == "critical"` OR
`case_type == "phishing_or_social_engineering"`.

### Safety rule

`agent_summary` is **never** allowed to contain the words `PIN`, `OTP`,
`password`, or `card number` (plus `cvv` / `cvc` for belt-and-suspenders).
The classifier runs a regex pass on the summary before returning it and
redacts any forbidden tokens.

## Project layout

```
ticket-sorter/
├── main.py              # FastAPI app + routes
├── classifier.py        # Keyword rules, severity/department lookup, safety filter
├── models.py            # Pydantic request / response schemas
├── requirements.txt
├── Dockerfile
└── README.md
```

## Running locally

### 1. Install

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run

```bash
uvicorn main:app --reload --port 8000
```

Open <http://localhost:8000/docs> for the Swagger UI.

### 3. Quick smoke test

```bash
curl -s http://localhost:8000/health | jq

curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-001",
        "message": "I sent 5000 taka to a wrong number by mistake."
      }' | jq

curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-002",
        "message": "Someone called me and asked for my OTP to verify my bKash account."
      }' | jq

curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-003",
        "message": "My payment failed but money was deducted from my account."
      }' | jq
```

## Running with Docker

```bash
docker build -t ticket-sorter .

docker run --rm -p 8000:8000 ticket-sorter
```

No env vars required — the classifier is fully offline.

## Configuration

| Env var     | Required | Default | Notes                                |
| ----------- | -------- | ------- | ------------------------------------ |
| `LOG_LEVEL` | no       | `INFO`  | `DEBUG`, `INFO`, `WARNING`, `ERROR`  |

## Deploying to Render

Render can run this service directly from the `Dockerfile` — no buildpack
or `render.yaml` is needed.

### Option A: One-click from the dashboard

1. Push the repo to GitHub and sign in at <https://dashboard.render.com>.
2. Click **New + → Web Service**, then pick **"Build and deploy from a Git repository"**.
3. Select the `PoishaGo` repo and the `ticket-sorter` (or root) directory.
4. On the create form set:
   - **Runtime**: `Docker`
   - **Region**: any (e.g. `Singapore` for low latency in BD)
   - **Instance type**: `Free` is fine for a demo
   - **Health check path**: `/health`
5. Skip the **Environment** section — there are no required env vars. You can
   optionally add `LOG_LEVEL=INFO`.
6. Click **Create Web Service**. The first build uses the `Dockerfile` in this
   repo (`python:3.12-slim` → `pip install -r requirements.txt` → `uvicorn`).

   Render will auto-assign a URL like `https://ticket-sorter.onrender.com`.
   Swagger UI is served at `/docs`.

### Option B: Blueprint (`render.yaml`)

If you prefer infra-as-code, drop a `render.yaml` next to the `Dockerfile`:

```yaml
services:
  - type: web
    name: ticket-sorter
    runtime: docker
    plan: free
    healthCheckPath: /health
    dockerContext: .
    dockerfilePath: ./Dockerfile
```

Then in the dashboard choose **New + → Blueprint**, point it at the repo, and
Render will read the file and create the service for you.

### Verifying the deploy

Once Render shows the service as **Live**, smoke test from any terminal:

```bash
SERVICE=https://ticket-sorter.onrender.com   # replace with your URL

curl -s $SERVICE/health | jq

curl -s -X POST $SERVICE/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-001",
        "message": "I sent 5000 taka to a wrong number by mistake."
      }' | jq
```

### Render gotchas to know about

- **Free tier sleeps after 15 min of inactivity** — the first request after a
  sleep takes ~30 s. Keep it warm with a cron ping or upgrade to the
  `Starter` plan for always-on.
- **Port binding**: Render injects `PORT` (defaults to `10000`) and expects the
  app to bind to `0.0.0.0:$PORT`. The `Dockerfile`'s
  `CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]`
  hard-codes `8000`, which works because Render also exposes `8000` for Docker
  services. If you switch to a buildpack later, change it to read `PORT` from
  the env, e.g. `uvicorn main:app --host 0.0.0.0 --port $PORT`.
- **No env files needed** — the classifier is fully offline, so there is
  nothing to put in Render's **Environment** tab.
- **Logs**: Render's **Logs** tab streams the same `LOG_LEVEL` output the
  container writes to stdout, so `LOG_LEVEL=DEBUG` is useful when debugging a
  new keyword list.

## Notes for the hackathon

- Classification is **deterministic and synchronous**: same input → same output,
  every time. No cold starts, no rate limits, no network.
- `confidence` reflects how strong the keyword match was
  (`0.9` for phishing, `0.85` for wrong-transfer / payment-failed,
  `0.8` for refund, `0.5` for `other`).
- The keyword lists live in `classifier.py` at the top — easy to extend
  during the demo without restarting anything.
- The safety filter is implemented as a regex pass over the generated
  summary; it always runs even though there is no LLM to violate it.
