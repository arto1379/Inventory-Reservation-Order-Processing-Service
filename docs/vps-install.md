# Installing on a VPS

Deploying the Docker-based stack (Postgres, Redis, API, Celery worker, Celery
Beat, outbox relay) onto a fresh Ubuntu/Debian VPS. This is the same
`docker compose up --build` flow as local dev (see `README.md`), just with a
production `.env` and the box locked down first.

Assumes a fresh Ubuntu 22.04/24.04 VPS with a non-root sudo user already
created and SSH key access working. For hardening the box itself (firewall,
SSH, TLS, exposed ports), see `docs/vps-security.md` — do that alongside or
right after this, before pointing real traffic at it.

## 1. Install Docker Engine + Compose plugin

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Run docker without sudo (log out/in once for this to take effect)
sudo usermod -aG docker $USER
```

Verify: `docker compose version` and `docker run hello-world`.

## 2. Get the code onto the box

```bash
git clone <your-repo-url> ponytail
cd ponytail
```

If the repo is private, either set up a deploy key or push a release tarball
instead of cloning — don't put long-lived personal credentials on the VPS.

## 3. Configure `.env` for production

```bash
cp .env.example .env
```

Edit `.env` and change at minimum:

- `ENVIRONMENT=production`
- `JWT_SECRET` — a long random value, not the placeholder. Generate one with
  `openssl rand -hex 32`.
- `DEFAULT_ADMIN_PASSWORD` — not `ChangeMe123!`. Rotate it (or the account)
  after first login if you'd rather not keep it in `.env` long-term.
- Leave `DATABASE_URL`/`REDIS_URL` pointing at the `postgres`/`redis` service
  names — those only need to change if you're pointing at externally-hosted
  Postgres/Redis instead of the bundled containers.

`.env` is already git-ignored; keep it that way and never commit the
production values. Lock down its permissions:

```bash
chmod 600 .env
```

## 4. Bring the stack up

```bash
docker compose up --build -d
```

This builds the image once and reuses it for the `api`, `worker`, `beat`,
and `outbox-relay` services (see `Dockerfile`'s header comment). The `api`
service runs `alembic upgrade head` then `python -m src.bootstrap` before
starting uvicorn, so migrations and the default admin user are handled
automatically on first boot — no manual migration step needed.

## 5. Verify

```bash
docker compose ps                     # all 5 services should be "running"/"healthy"
docker compose logs -f api            # watch startup logs
curl -s http://localhost:8000/docs -o /dev/null -w "%{http_code}\n"   # expect 200
```

Get an admin token to confirm end-to-end:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"'"$(grep DEFAULT_ADMIN_EMAIL .env | cut -d= -f2)"'","password":"'"$(grep DEFAULT_ADMIN_PASSWORD .env | cut -d= -f2)"'"}'
```

Do **not** stop here with port 8000 open to the world — by default
`docker-compose.yml` publishes `8000`, `5432`, and `6379` on all interfaces.
Follow `docs/vps-security.md` to put a reverse proxy with TLS in front of
the API and bind Postgres/Redis to localhost only before this box is
reachable from the internet.

## 6. Updating a deployment later

```bash
git pull
docker compose up --build -d
```

Compose recreates only the containers whose image/config changed. Migrations
run again on `api` startup automatically (`alembic upgrade head` is
idempotent against an already-migrated schema).

## Troubleshooting

- `docker compose ps` shows `api` restarting: check
  `docker compose logs api` — almost always a bad `DATABASE_URL`/`REDIS_URL`
  or a migration failure.
- `docker: permission denied`: you ran a `docker` command before logging out
  and back in after `usermod -aG docker`. Log out/in (or `newgrp docker`)
  once.
- Low-memory VPS (1 GB or less) can OOM during `pip install` inside the
  build; add swap first (`fallocate -l 2G /swapfile && chmod 600 /swapfile
  && mkswap /swapfile && swapon /swapfile`).
