# AskTube AI — AWS EC2 Deployment Guide

This guide deploys the full stack (Next.js frontend, FastAPI backend, ChromaDB) on a
single EC2 instance behind an Nginx reverse proxy, with optional HTTPS via Certbot.

---

## 1. EC2 Instance Setup

### Recommended specs

| Field | Value |
|---|---|
| AMI | Ubuntu 24.04 LTS (x86_64) |
| Instance type | `t3.medium` (2 vCPU, 4 GB RAM) — minimum; `t3.large` for comfort |
| Storage | 20 GB gp3 root volume |
| Key pair | Create or select an existing `.pem` key |

### Security group — inbound rules

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | Your IP | SSH |
| 80 | TCP | 0.0.0.0/0 | HTTP / Certbot challenge |
| 443 | TCP | 0.0.0.0/0 | HTTPS (after SSL setup) |

> Do **not** expose ports 3000, 8000, or 8001 publicly — Nginx proxies everything through 80/443.

### Connect

```bash
chmod 400 your-key.pem
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

---

## 2. Install Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
     -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
     docker-buildx-plugin docker-compose-plugin

# Allow running docker without sudo
sudo usermod -aG docker ubuntu
newgrp docker

# Verify
docker --version
docker compose version
```

---

## 3. Clone the Repository

```bash
cd /home/ubuntu
git clone https://github.com/<your-org>/asktube-ai.git
cd asktube-ai
```

---

## 4. Configure Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
nano .env
```

Required values to set:

```dotenv
# API Keys
YOUTUBE_API_KEY=<your-youtube-data-api-v3-key>
OPENAI_API_KEY=<your-openai-api-key>

# Frontend URL — set to your EC2 public IP or domain
NEXT_PUBLIC_API_URL=http://<EC2_PUBLIC_IP_OR_DOMAIN>

# CORS — must match the URL your browser uses to reach the app
CORS_ORIGINS=http://<EC2_PUBLIC_IP_OR_DOMAIN>

# ChromaDB — Docker service name, do not change
CHROMA_USE_HTTP=true
CHROMA_HOST=chromadb
CHROMA_PORT=8000
CHROMA_COLLECTION_NAME=asktube_videos

# Models
WHISPER_MODEL=whisper-1
CHAT_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

# Optional — LangSmith tracing
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
```

> **Never commit `.env` to git.** It is already in `.gitignore`.

---

## 5. Build and Start the Stack

### Without Nginx (quick test — direct port access)

```bash
docker compose up -d --build
```

Services will be reachable at:
- Frontend: `http://<EC2_PUBLIC_IP>:3000`
- Backend: `http://<EC2_PUBLIC_IP>:8000`

> You will need to temporarily open ports 3000 and 8000 in the security group for this.

### With Nginx (recommended)

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build
```

The app is now reachable at `http://<EC2_PUBLIC_IP>` on port 80.

---

## 6. Nginx Reverse Proxy

The Nginx config is at `nginx/asktube.conf`. It proxies:

| Path | Target |
|---|---|
| `/api/*` | FastAPI backend (port 8000) |
| `/*` | Next.js frontend (port 3000) |

WebSocket upgrades (`/api/chat/stream`, `/api/videos/*/ingest/stream`) are handled automatically via the `Upgrade` / `Connection` headers.

No changes are needed unless you add a custom domain — in that case update `server_name`:

```nginx
server_name yourdomain.com www.yourdomain.com;
```

---

## 7. Optional — HTTPS with Certbot

> Requires a real domain pointed at your EC2 IP via an A record.

### Point your domain

In your DNS provider, add an A record:

```
yourdomain.com  →  <EC2_PUBLIC_IP>
```

Wait for DNS to propagate (~5 minutes), then verify:

```bash
dig +short yourdomain.com
```

### Update Nginx config for HTTPS

Edit `nginx/asktube.conf` to add the SSL server block:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    # Certbot ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect all HTTP to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name yourdomain.com www.yourdomain.com;

    ssl_certificate     /etc/nginx/ssl/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/live/yourdomain.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location / {
        proxy_pass http://frontend:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Also update `.env`:

```dotenv
NEXT_PUBLIC_API_URL=https://yourdomain.com
CORS_ORIGINS=https://yourdomain.com
```

### Issue the certificate

```bash
mkdir -p nginx/ssl

docker compose -f docker-compose.yml -f docker-compose.nginx.yml run --rm certbot \
  certbot certonly --webroot \
  -w /var/www/certbot \
  -d yourdomain.com \
  -d www.yourdomain.com \
  --email your@email.com \
  --agree-tos \
  --no-eff-email
```

### Restart Nginx to load the certificate

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml restart nginx
```

Certificates auto-renew every 12 hours via the `certbot` sidecar container.

---

## 8. Webshare Residential Proxy (Recommended on EC2)

AWS EC2 IP addresses are well-known cloud ranges. YouTube blocks transcript
extraction from them. Without a residential proxy you will get
`TranscriptsDisabled` or `NoTranscriptFound` errors for most videos.

### Why it's needed

| Environment | YouTube transcript access |
|---|---|
| Local machine (home IP) | Works without proxy |
| EC2 / cloud server | Blocked — residential proxy required |

### Get Webshare credentials

1. Sign up at [webshare.io](https://www.webshare.io) and subscribe to a
   **Residential** proxy plan (the cheapest tier is sufficient).
2. Go to **Proxy** → **Residential** → **Username / Password** and copy your
   credentials.
3. Note the country codes you want to route through (e.g. `US`, `DE`, `GB`).

### Add to `.env`

```dotenv
# Webshare residential proxy — required on EC2 for transcript extraction
WEBSHARE_PROXY_USERNAME=<your-webshare-username>
WEBSHARE_PROXY_PASSWORD=<your-webshare-password>
WEBSHARE_PROXY_LOCATIONS=US,GB   # comma-separated ISO country codes, or leave blank for any
```

`WEBSHARE_PROXY_LOCATIONS` is optional. Leave it blank to use any available
exit node; set one or more country codes to pin to a specific region (useful
for geo-restricted content).

### How it works

The backend picks up the credentials automatically at startup:

- **Credentials present** → `YouTubeTranscriptApi` routes all transcript
  requests through Webshare's residential pool with 5 automatic retries on
  block.
- **Credentials absent** → direct connection (works on localhost, fails on EC2).

No code change or container rebuild is required — only the `.env` values need
to be set. Restart the backend after updating `.env`:

```bash
docker compose restart backend
```

Verify the proxy is active:

```bash
docker compose exec backend env | grep WEBSHARE
```

### Troubleshooting proxy issues

**`NoTranscriptFound` on EC2 despite setting credentials**
- Confirm the variables are actually loaded: `docker compose exec backend env | grep WEBSHARE`
- Check you copied the **Residential** credentials, not the Datacenter ones.
- Try adding `US` to `WEBSHARE_PROXY_LOCATIONS` — some videos are only
  accessible from US exit nodes.

**`407 Proxy Authentication Required` in logs**
- Username or password is wrong. Re-copy from the Webshare dashboard.

**Proxy works but is slow**
- Residential proxies add ~200–500 ms latency per transcript request. This is
  normal and only affects the initial transcript fetch, not chat responses.

---

## 9. Managing the Stack

### Start

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d
```

### Stop

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml down
```

### Restart a single service

```bash
docker compose restart backend
docker compose restart frontend
docker compose restart nginx
```

### Rebuild after a code change

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build frontend backend
```

Only the changed images are rebuilt; ChromaDB and Nginx are untouched.

### Start on system boot

Docker is already configured to start on boot by the install script. Containers with
`restart: unless-stopped` come back up automatically after a reboot.

To reboot the instance safely:

```bash
sudo reboot
# wait ~60 seconds, then SSH back in
docker compose -f docker-compose.yml -f docker-compose.nginx.yml ps
```

---

## 10. Checking Logs

```bash
# All services, live
docker compose logs -f

# One service
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f nginx
docker compose logs -f chromadb

# Last 100 lines
docker compose logs --tail=100 backend
```

---

## 11. Troubleshooting

### Backend returns 503 "YOUTUBE_API_KEY is not configured"
The `.env` file is missing or the key is blank. Check:
```bash
docker compose exec backend env | grep YOUTUBE
```

### Frontend shows a blank page or loads at the bottom
- Confirm `NEXT_PUBLIC_API_URL` in `.env` matches the URL your browser uses.
- This value is baked into the Next.js bundle at build time — you must rebuild
  the frontend image after changing it:
  ```bash
  docker compose up -d --build frontend
  ```

### ChromaDB connection refused
The backend connects to ChromaDB by service name. Verify:
```bash
docker compose exec backend python -c "
import chromadb
c = chromadb.HttpClient(host='chromadb', port=8000)
print(c.heartbeat())
"
```

### Port 80 already in use
Another process (e.g., Apache) is bound to port 80:
```bash
sudo lsof -i :80
sudo systemctl stop apache2   # or nginx if installed system-wide
```

### Container keeps restarting
```bash
docker compose ps                        # check STATUS column
docker compose logs --tail=50 <service>  # read the error
```

### Out of disk space
```bash
df -h
docker system prune -f          # remove unused images and stopped containers
docker volume prune -f          # WARNING: removes unused volumes
```

### SSL certificate not found by Nginx
The certificate path must match `server_name`. Check:
```bash
docker compose exec nginx ls /etc/nginx/ssl/live/
```
The directory name must exactly match the domain in your Nginx config.

---

## Quick Reference

| Task | Command |
|---|---|
| Start stack | `docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d` |
| Stop stack | `docker compose down` |
| View all logs | `docker compose logs -f` |
| Rebuild after push | `docker compose up -d --build frontend backend` |
| Check container health | `docker compose ps` |
| Open a shell | `docker compose exec backend bash` |
| Check env vars | `docker compose exec backend env` |
