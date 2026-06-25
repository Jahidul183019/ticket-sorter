# ticket-sorter

A small FastAPI service that classifies customer support tickets for a digital
finance company (think bKash / Nagad / mobile-money wallets). Each incoming
message is routed to the right team — customer support, dispute resolution,
payments ops, or fraud risk — using pure Python keyword rules.

**No LLM. No API key. No external calls.** Just if/elif/else on the message
text, so the demo runs offline.

> Built as a submission for the **SUST CSE Preliminary Mock Contest** — a
> take-home style build where reliability and demo-readiness matter more than
> model nuance. The whole service is offline, deterministic, and boots in
> under a second on the free tier of any host.

## Endpoints

| Method | Path           | Purpose                                        |
| ------ | -------------- | ---------------------------------------------- |
| GET    | `/health`      | Liveness probe (`{"status":"ok", ...}`)        |
| POST   | `/sort-ticket` | Classify a customer message and return routing |
| GET    | `/docs`        | Auto-generated Swagger UI                      |

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
  "human_review_required": false,
  "confidence": 0.85
}
```

`human_review_required` is `true` **only** when `severity = "critical"` or
`case_type = "phishing_or_social_engineering"`. A `severity = "high"` case
such as a wrong transfer does **not** trigger human review on its own.

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

`human_review_required = true` **only if**:
- `severity == "critical"` (phishing cases), OR
- `case_type == "phishing_or_social_engineering"`

All other cases — including `high` severity — return `human_review_required: false`.

### Safety rule

`agent_summary` is **never** allowed to contain the words `PIN`, `OTP`,
`password`, `card number`, `cvv`, or `cvc`. The classifier runs a regex pass
on the summary before returning it and redacts any forbidden tokens.

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
# Health check
curl -s http://localhost:8000/health | jq

# Case 1: wrong transfer → high severity, human_review_required: false
curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-001",
        "message": "I sent 5000 taka to a wrong number by mistake."
      }' | jq

# Case 2: phishing → critical severity, human_review_required: true
curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-002",
        "message": "Someone called me and asked for my OTP to verify my bKash account."
      }' | jq

# Case 3: payment failed → high severity, human_review_required: false
curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-003",
        "message": "My payment failed but money was deducted from my account."
      }' | jq

# Case 4: refund request → low severity, human_review_required: false
curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-004",
        "message": "Please refund my last transaction, I changed my mind."
      }' | jq

# Case 5: other → low severity, human_review_required: false
curl -s -X POST http://localhost:8000/sort-ticket \
  -H 'Content-Type: application/json' \
  -d '{
        "ticket_id": "T-005",
        "message": "App crashed when I opened it."
      }' | jq
```

## Running with Docker

```bash
docker build -t ticket-sorter .
docker run --rm -p 8000:8000 ticket-sorter
```

No env vars required — the classifier is fully offline.

## Configuration

| Env var     | Required | Default | Notes                               |
| ----------- | -------- | ------- | ----------------------------------- |
| `LOG_LEVEL` | no       | `INFO`  | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

## Notes for the hackathon

- Classification is **deterministic and synchronous**: same input → same output,
  every time. No cold starts, no rate limits, no network dependency.
- `confidence` reflects keyword match strength: `0.9` for phishing, `0.85` for
  wrong-transfer / payment-failed, `0.8` for refund, `0.5` for `other`.
- The keyword lists live at the top of `classifier.py` — easy to extend during
  the demo without restarting.
- The safety filter (regex redaction of PIN/OTP/password/card number) always
  runs even though there is no LLM to violate it.
- **LLM used:** No.