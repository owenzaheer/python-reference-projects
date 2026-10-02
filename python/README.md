# Python demos

Python 3.12+. From this folder: `python -m venv .venv`, activate it, then `python -m pip install -r requirements.txt`.

FastAPI projects: `python run.py financial-reconciliation-and-exception-workbench-python --port 8000` or use the assessment folder name. Open `http://127.0.0.1:8000` for the workflow console and `/docs` for typed request contracts.

The ecommerce project is Django/DRF with a browser console and transactional CSV imports. Run `python ecommerce-fulfillment-and-exception-portal-python/manage.py runserver 127.0.0.1:8000`.

Data: SQLite, in memory by default. Set `DEMO_DATABASE=local.db` to persist FastAPI/Django workflow state. State/audit access requires `Authorization: Bearer local-operator`. Action requests use the appropriate local fixture role: learner, operator, reviewer or instructor. These explicit development tokens are not real authentication.

Run `python -m pytest -q` here. Tests cover stock concurrency, replay conflicts, rollback on relay failure, callback signatures, approval races, deterministic scoring, deadlines, permissions and persistent reopening.

## Signed finance fixture

From this folder, generate a callback payload without storing a real credential:

```python
import json
from core import Engine
body={"id":"PAY-1","invoice":"INV-100","amount":10000}
print(json.dumps({**body,"signature":Engine().signature(body)}))
```

Paste it into the callback command. The shared signing key is intentionally a local fixture; production secrets must be external and rotated.

Implemented: Python/FastAPI/Pydantic, Django/DRF, SQLite, standard-library HMAC/CSV, pytest. PostgreSQL, Redis, Celery, BotCity, cloud hosting and model services are not live integrations in these local demos.
