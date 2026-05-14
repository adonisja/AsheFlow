# Engineering Journal: 2026-05-14

**Session Start Time**: ~02:00 EST
**Session End Time**: ~ongoing

## Goal for the Session

Deploy AsheFlow to production for the first time. This means:
1. A real server on AWS EC2 running the backend API
2. The frontend hosted on S3 + CloudFront
3. All services (backend, bot, Celery, Redis, Postgres) running together via Docker Compose

## What We Did and Why

### Step 1: Launched an EC2 instance

**What:** We created a virtual server on AWS EC2.

**Why:** The backend (FastAPI), database (PostgreSQL), cache (Redis), task queue (Celery), and Discord bot all need to run somewhere. EC2 is a virtual machine in AWS's data center — it's always on, has a public IP address, and can run Docker.

**Decisions made:**
- **Ubuntu 26.04 LTS** — the current stable long-term support Linux OS. LTS means it gets security updates for 5 years.
- **t3.small** — 2 vCPUs, 2 GB RAM, ~$15/month. t3.micro (1 GB) was ruled out because the full stack (6 services + Docker overhead) consumes 800 MB–1.2 GB at rest, leaving no headroom for traffic spikes.
- **20 GB gp3 storage** — enough for the OS, Docker images, and database data.
- **Security group** — a firewall that only allows: SSH (port 22) from our IP, HTTP (port 80) from anywhere, HTTPS (port 443) from anywhere. Port 8000 (FastAPI) is NOT open publicly — Nginx will proxy traffic from 443 to 8000 internally.
- **Key pair** — a `.pem` file that acts as the "key" to SSH into the server. Downloaded once, stored at `~/.ssh/asheflow-key.pem` with permissions `400` (read-only by owner).
- **IAM role (`asheflow-ec2-role`)** — grants the EC2 instance permission to write logs to CloudWatch. Without this role, Docker's `awslogs` log driver fails and the containers won't start.

**First instance was terminated** (from a previous session). A second instance was launched at IP `3.141.169.13`.

---

### Step 2: Installed Docker on the server

**What:** Installed Docker Engine and the Docker Compose plugin on the EC2 instance.

**Why:** The entire AsheFlow stack is containerized. Docker runs each service (backend, postgres, redis, celery, bot) in an isolated container. Docker Compose orchestrates all of them together from a single `docker-compose.yml` file.

**Problem encountered:** Ubuntu 26.04's default package repositories don't yet have `docker-compose-plugin`. Solution: added Docker's official apt repository (with GPG key verification) and installed from there instead.

**Commands that matter:**
```bash
# Add Docker's official repo
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=...] https://download.docker.com/linux/ubuntu <codename> stable" | sudo tee ...

# Install
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow ubuntu user to run docker without sudo
sudo usermod -aG docker ubuntu && newgrp docker
```

---

### Step 3: Cloned the repo

**What:** Downloaded the AsheFlow codebase onto the server with `git clone`.

**Why:** The server needs the code, Dockerfiles, and docker-compose files to build and run the containers.

**Authentication:** GitHub no longer accepts passwords for git operations. Used a fine-grained Personal Access Token scoped to the AsheFlow repo with read-only Contents permission — least privilege principle.

---

### Step 4: Created .env files (previous instance — needs to be repeated)

**What:** Created two `.env` files with real secrets and config values:
- `.env` — read by Docker Compose to inject environment variables into containers
- `backend/.env` — read by the FastAPI `Settings()` class at startup
- `bot/.env` — read by the Discord bot's `Settings()` class at startup

**Why separate files:** Docker Compose reads the root `.env` for variables like `POSTGRES_PASSWORD` that it uses to configure the postgres container. The backend reads `backend/.env` directly via pydantic-settings. They serve different purposes.

**Key values set:**
- `POSTGRES_PASSWORD` — random 32-byte hex, generated with `secrets.token_hex(32)`
- `SECRET_KEY` — random 32-byte hex
- `INTERNAL_SECRET` — random 32-byte hex, **must match in both backend/.env and bot/.env** — used to authenticate bot → backend webhook calls
- `APP_ENV=production` — triggers ENV-2 and ENV-3 startup guards
- `CORS_ORIGINS=https://asheflow.com,https://www.asheflow.com` — only the real domain, no localhost
- `AWS_COGNITO_USER_POOL_ID=us-east-2_SvVO2ofAb` — the Cognito pool that issues JWTs
- `BOT_USERNAME=asheflow.bot` / `BOT_PASSWORD=sxVONWQeHlxvfKpg8ZCu!` — the bot's Cognito service account

**Bot Cognito account:** `asheflow.bot` had been deleted. Recreated via AWS CLI:
```bash
aws cognito-idp admin-create-user --user-pool-id us-east-2_SvVO2ofAb --username asheflow.bot --temporary-password 'sxVONWQeHlxvfKpg8ZCu!' --message-action SUPPRESS --region us-east-2
aws cognito-idp admin-set-user-password --user-pool-id us-east-2_SvVO2ofAb --username asheflow.bot --password 'sxVONWQeHlxvfKpg8ZCu!' --permanent --region us-east-2
```
`--permanent` skips the forced password change on first login. `--message-action SUPPRESS` prevents a welcome email from being sent to a non-existent address.

---

## Problems Encountered and Fixed

**Problem 1 — `docker-compose-plugin` not in Ubuntu 26.04 default repos**
`sudo apt install docker-compose-plugin` returned "unable to locate package." Fix: added Docker's official apt repository with GPG key verification, then installed `docker-ce docker-ce-cli containerd.io docker-compose-plugin` from there.

**Problem 2 — First EC2 instance terminated**
The first instance (`107.23.166.19`) was terminated between sessions. Launched a second instance (`3.141.169.13`) with the IAM role attached at launch this time.

**Problem 3 — `Settings()` crashed with `Extra inputs are not permitted`**
Alembic migration failed because the backend container was built from the old `python:3.11-slim` Dockerfile. The `3.11` image had an older version of the code (before `app_env` and `bot_internal_url` were added to `Settings`). Fix: the Dockerfile fix commit hadn't been pushed to GitHub. Pushed it, pulled on the server, rebuilt with `--no-cache`.

**Problem 4 — Alembic revision ID too long for `VARCHAR(32)`**
Migration `20260409_add_expired_status_to_time_off_requests` (50 chars) exceeded the `alembic_version` table's `version_num VARCHAR(32)` column. The schema change applied successfully but the version write failed. Fix: shortened the revision ID to `add_expired_tor` in the migration file and all two dependent files that referenced it as `down_revision`.

**Problem 5 — `awslogs-stream-prefix` not supported**
Docker's awslogs driver on Ubuntu 26.04 does not support the `awslogs-stream-prefix` option despite Docker 29.3.1 being installed. Error: `unknown log opt 'awslogs-stream-prefix' for awslogs log driver`. Diagnosed by testing options directly with `docker run --log-driver=awslogs`. Fix: replaced `awslogs-stream-prefix` with `awslogs-stream` in `docker-compose.prod.yml`.

**Problem 6 — CloudWatch log group didn't exist**
The awslogs driver requires the log group to exist before containers start. Created it manually: `aws logs create-log-group --log-group-name /asheflow/production --region us-east-2`.

**Problem 7 — Default region was `us-east-1` in `docker-compose.prod.yml`**
The YAML anchor used `${AWS_REGION:-us-east-1}` but all AWS infrastructure is in `us-east-2`. Fixed the default and added `AWS_REGION=us-east-2` to `.env` on the server.

**Problem 8 — `confirmation_window_hours` was a dead config value**
`bot/config.py` had `confirmation_window_hours: int = 2` but it was never referenced anywhere in the bot code. No enforcement logic existed. Removed from config entirely. When the feature is built, it will be added to the `company_configs` table as a per-company setting.

## Final State

All 5 containers running:
- `asheflow_backend` — FastAPI on port 8000, 4 uvicorn workers
- `asheflow_celery_worker` — processes async tasks
- `asheflow_celery_beat` — fires scheduled jobs (separate from worker to prevent double-firing)
- `asheflow_postgres` — PostgreSQL, healthy
- `asheflow_redis` — Redis, healthy

Health check confirmed: `curl http://localhost:8000/health` → `{"status":"ok"}`

All container logs shipping to CloudWatch log group `/asheflow/production` in `us-east-2`.

## Additional Steps Completed

**Nginx + SSL for `api.asheflow.com`:**
1. Installed `nginx certbot python3-certbot-nginx` on the server
2. Created `/etc/nginx/sites-available/asheflow` — proxies all traffic from port 80/443 to `127.0.0.1:8000`
3. Enabled with `sudo ln -s /etc/nginx/sites-available/asheflow /etc/nginx/sites-enabled/`
4. Added Route 53 A record: `api` → `3.141.169.13`, TTL 300
5. Confirmed HTTP reachable: `curl http://api.asheflow.com/health` → `{"status":"ok"}`
6. Ran `sudo certbot --nginx -d api.asheflow.com` — issued Let's Encrypt certificate, Nginx config auto-updated with SSL blocks
7. Confirmed HTTPS reachable: `curl https://api.asheflow.com/health` → `{"status":"ok"}`

**Discord bot:**
The bot was not in `docker-compose.yml` — it had a `Dockerfile` but was being run as an orphan container from a previous session. Added as a proper service with `env_file: ./bot/.env`, `depends_on: backend`, and `restart: unless-stopped`. Also bumped `bot/Dockerfile` from `python:3.11-slim` to `python:3.12-slim`.

Bot startup confirmed via `docker logs asheflow_bot`:
- Cognito token refreshed (authenticated as `asheflow.bot`)
- IAM role credentials found automatically from EC2 metadata
- Connected to Discord Gateway
- Logged in as `AsheFlow Dispatch#9457`
- Synced 1 slash command to guild

**Final running state — all 6 containers:**
- `asheflow_backend` — FastAPI at `https://api.asheflow.com`, 4 workers
- `asheflow_bot` — Discord bot online
- `asheflow_celery_worker` — task queue
- `asheflow_celery_beat` — scheduled jobs
- `asheflow_postgres` — healthy
- `asheflow_redis` — healthy

## What Still Needs to Be Done

1. Build frontend with `.env.production`, upload to S3, set up CloudFront for `asheflow.com`

## Key Takeaways

- EC2 is just a virtual machine — a computer in AWS's data center that you configure and control via SSH.
- A security group is a firewall. It controls which ports are reachable from the internet. Never open a port unless something needs to reach it from outside.
- An IAM role grants an AWS service (like EC2) permission to call other AWS services (like CloudWatch). Without the role, the EC2 instance has no AWS permissions at all.
- Docker Compose reads a root `.env` file automatically. The backend's pydantic Settings reads `backend/.env` separately. They are not the same file.
- `INTERNAL_SECRET` is the shared secret between the backend and the bot. If they don't match, every bot → backend call returns 403. Both files must have the same value.
- A fine-grained GitHub token scoped to one repo with read-only access is the correct credential for a server that only needs to clone and pull — it cannot push, cannot access other repos, and can be revoked without affecting anything else.
- `--permanent` on `admin-set-user-password` is required to skip the forced-change flow that would block the bot from authenticating on first login.
- Alembic revision IDs must be 32 characters or fewer — the `alembic_version` table has a `VARCHAR(32)` column. Date-prefixed IDs like `20260409_add_expired_status_to_time_off_requests` exceed this. Use short descriptive IDs.
- Always push local commits to GitHub before deploying. A server `git pull` that says "already up to date" when you expect new code means the commits exist locally but were never pushed.
- `awslogs-stream-prefix` is not supported by all builds of the Docker awslogs driver. Use `awslogs-stream` instead — it is universally supported and achieves the same result.
- The CloudWatch log group must exist before containers start with the awslogs driver. Create it with `aws logs create-log-group` before the first `docker compose up`.
- Always use the same AWS region consistently across all config files, IAM policies, log groups, and env vars. Mixing `us-east-1` and `us-east-2` causes silent failures where requests hit the wrong region and find nothing.
- Dead config values are a maintenance liability even when harmless. `confirmation_window_hours` was defined but never used — it would have sat in `.env` files and config classes indefinitely, confusing future developers. Remove dead config as soon as it's identified.
