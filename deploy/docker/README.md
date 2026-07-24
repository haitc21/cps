# Local development infrastructure

This Compose stack provides the shared local dependencies for CPS and OPS:

- PostgreSQL for CPS persistence
- RabbitMQ with the management UI for CPS/OPS messaging

All published ports bind to `127.0.0.1` and are not exposed to the LAN.

## Start

Copy `.env.example` to `.env`, change the development passwords if needed, and
then run:

```bash
docker compose up -d --wait
docker compose ps
```

This also builds and starts the CPS public API (`:8000`), CPS internal
credential resolver (`:8002`), CPS worker, OPS API (`:8001`), and OPS worker.
OPS connects to the resolver through the Docker service name
`http://cps-internal:8002`.

For a credential-resolution demo, set a synthetic local key in `.env` before
starting the services. The key is development-only and must never be reused in
production:

```bash
python -c "import base64; print('v1:' + base64.b64encode(b'k' * 32).decode())"
```

Copy the printed value into `CPS_CREDENTIAL_KEY_RING`. Host processes use
`http://127.0.0.1:8002`; containers use `http://cps-internal:8002`.

Run the commands from this directory. RabbitMQ Management is available at
<http://127.0.0.1:15672>.

Default local connection values when no `.env` file is present:

```text
PostgreSQL: postgresql://cps:cps_dev_password@127.0.0.1:5432/cps
RabbitMQ:   amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp
```

CPS runtime settings for the same stack:

```text
CPS_ENVIRONMENT=development
CPS_DATABASE_URL=postgresql+psycopg://cps:cps_dev_password@127.0.0.1:5432/cps
CPS_RABBITMQ_URL=amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp
```

CPS readiness (`/health/ready`) depends on PostgreSQL and RabbitMQ only.

## Stop

```bash
docker compose down
```

`docker compose down` stops containers and preserves named volumes.
