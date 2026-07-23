# Local development infrastructure

This Compose stack provides the shared local dependencies for CPS and OPS:

- PostgreSQL for CPS persistence
- RabbitMQ with the management UI for CPS/OPS messaging
- Valkey for future CMP integration; CPS/OPS do not depend on it initially

All published ports bind to `127.0.0.1` and are not exposed to the LAN.

## Start

Optionally copy `.env.example` to `.env` and change the development passwords,
then run:

```bash
docker compose up -d --wait
docker compose ps
```

This also builds and starts the CPS public API (`:8000`), CPS internal
credential resolver (`:8002`), CPS worker, OPS API (`:8001`), and OPS worker.
OPS connects to the resolver through the Docker service name
`http://cps-internal:8002`.

Run the commands from this directory. RabbitMQ Management is available at
<http://127.0.0.1:15672>.

Default local connection values when no `.env` file is present:

```text
PostgreSQL: postgresql://cps:cps_dev_password@127.0.0.1:5432/cps
RabbitMQ:   amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp
Valkey:     valkey://:valkey_dev_password@127.0.0.1:6379/0
```

CPS runtime settings for the same stack:

```text
CPS_ENVIRONMENT=development
CPS_DATABASE_URL=postgresql+psycopg://cps:cps_dev_password@127.0.0.1:5432/cps
CPS_RABBITMQ_URL=amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp
```

CPS readiness (`/health/ready`) depends on PostgreSQL and RabbitMQ only.
Valkey remains available for future CMP services and is not a CPS readiness
dependency.

## Stop

```bash
docker compose down
```

`docker compose down` stops containers and preserves named volumes.
