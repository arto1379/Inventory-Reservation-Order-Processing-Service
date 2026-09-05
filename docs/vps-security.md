# Hardening a VPS deployment

Follow this alongside/after `docs/vps-install.md`, before the box takes real
traffic. `docker-compose.yml` as checked in is a local-dev stack: it
publishes `postgres` (5432), `redis` (6379), and `api` (8000) on all
interfaces, uses a self-signed-nothing plain-HTTP API, and the default
`.env.example` secrets are placeholders. None of that is safe to expose
directly to the internet as-is.

## 1. Firewall: only 22/80/443 reachable from outside

```bash
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH        # or `sudo ufw allow 2222/tcp` if you moved SSH's port
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Do **not** `ufw allow 8000`, `5432`, or `6379`. Postgres and Redis should
never be reachable from outside the box at all, and the API should only be
reachable through the reverse proxy on 80/443 (step 3), not directly on
8000.

## 2. Stop publishing Postgres/Redis/API ports to all interfaces

In `docker-compose.yml`, change the `ports:` mappings so Postgres and Redis
bind to localhost only (containers on the same Docker network can still
reach each other by service name regardless — this only affects host
port-forwarding):

```yaml
  postgres:
    ports:
      - "127.0.0.1:5432:5432"
  redis:
    ports:
      - "127.0.0.1:6379:6379"
  api:
    ports:
      - "127.0.0.1:8000:8000"
```

The `worker`, `beat`, and `outbox-relay` services don't publish any ports
today and need none. With this change plus the firewall in step 1, Postgres
and Redis become entirely unreachable from outside the box, and the API is
only reachable through whatever you bind to `127.0.0.1:8000` locally — i.e.
the reverse proxy in the next step.

## 3. Put a TLS-terminating reverse proxy in front of the API

Nginx + Let's Encrypt is the standard low-effort option:

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
```

`/etc/nginx/sites-available/api`:

```nginx
server {
    listen 80;
    server_name your-domain.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d your-domain.example.com   # provisions TLS, sets up auto-renewal, redirects 80->443
```

After this, the API is only reachable as `https://your-domain.example.com`,
never as `http://<ip>:8000`.

## 4. SSH hardening

`/etc/ssh/sshd_config`:

```
PasswordAuthentication no
PermitRootLogin no
```

```bash
sudo systemctl restart ssh
```

Confirm key-based login works in a *second* terminal before closing the
first — don't lock yourself out. Consider `fail2ban` for automated
brute-force protection on whatever port SSH listens on:

```bash
sudo apt-get install -y fail2ban
sudo systemctl enable --now fail2ban
```

## 5. Secrets

- `JWT_SECRET` in `.env` must be a long random value
  (`openssl rand -hex 32`), never the `.env.example` placeholder — anyone
  with that value can forge valid tokens for any user/role.
- `DEFAULT_ADMIN_PASSWORD` should not stay as `ChangeMe123!` — either set a
  strong value before first boot or log in once and rotate it, since
  `python -m src.bootstrap` only creates the account if no user with that
  email exists yet (it won't reset the password on a later boot).
- `chmod 600 .env` so only the deploying user can read it.
- Don't commit `.env` — it's already in `.gitignore`; double-check
  `git status` after any change to confirm it's still untracked.

## 6. Keep the host patched

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

Enables automatic security patches for the OS. Docker images themselves
aren't covered by this — periodically rebuild
(`docker compose up --build -d`) to pick up upstream `python:3.12-slim`,
`postgres:16-alpine`, and `redis:7-alpine` security patches.

## 7. Docker daemon notes

- The `docker` group grants effectively root-equivalent access (a container
  can bind-mount the host filesystem) — only add trusted admin accounts to
  it, per step in `vps-install.md`'s `usermod -aG docker`.
- `docker-compose.yml` bind-mounts the whole repo (`volumes: - .:/app`) into
  every service for local-dev convenience. On a production box this means
  anyone who can write to the repo directory can affect the running
  containers; keep the repo directory's ownership/permissions restricted to
  the deploying user.

## Checklist before going live

- [ ] `ufw status` shows only 22 (or your SSH port), 80, 443 allowed
- [ ] `curl http://<vps-ip>:8000` from *outside* the box fails to connect
- [ ] `curl http://<vps-ip>:5432` and `:6379` from outside the box fail to connect
- [ ] `https://your-domain.example.com/docs` loads with a valid cert
- [ ] `JWT_SECRET` and `DEFAULT_ADMIN_PASSWORD` are non-default values
- [ ] SSH password auth is disabled and key login is confirmed working
- [ ] `.env` is `chmod 600` and not tracked by git
