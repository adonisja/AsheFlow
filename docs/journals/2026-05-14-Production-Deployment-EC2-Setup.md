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

## What Still Needs to Be Done (on the new instance)

1. `cd AsheFlow` and recreate all three `.env` files
2. Start postgres + redis, run `alembic upgrade head`
3. Start all services with `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
4. Install Nginx + Certbot, configure reverse proxy for `api.asheflow.com`
5. Add Route 53 A record: `api.asheflow.com` → `3.141.169.13`
6. Build frontend with `.env.production`, upload to S3, set up CloudFront for `asheflow.com`

## Key Takeaways

- EC2 is just a virtual machine — a computer in AWS's data center that you configure and control via SSH.
- A security group is a firewall. It controls which ports are reachable from the internet. Never open a port unless something needs to reach it from outside.
- An IAM role grants an AWS service (like EC2) permission to call other AWS services (like CloudWatch). Without the role, the EC2 instance has no AWS permissions at all.
- Docker Compose reads a root `.env` file automatically. The backend's pydantic Settings reads `backend/.env` separately. They are not the same file.
- `INTERNAL_SECRET` is the shared secret between the backend and the bot. If they don't match, every bot → backend call returns 403. Both files must have the same value.
- A fine-grained GitHub token scoped to one repo with read-only access is the correct credential for a server that only needs to clone and pull — it cannot push, cannot access other repos, and can be revoked without affecting anything else.
- `--permanent` on `admin-set-user-password` is required to skip the forced-change flow that would block the bot from authenticating on first login.
