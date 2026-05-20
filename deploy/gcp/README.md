# Deploying BrainOS on Google Cloud (Compute Engine)

This folder contains everything you need to stand up BrainOS on a single GCE
VM in under 10 minutes. Everything runs in three Docker containers
(`backend`, `frontend`, `nginx`) behind nginx on port 80.

```
[ user ] ─http:80─▶ [ nginx ] ─┬─/api/*─▶ [ backend  (FastAPI :8081) ]
                                └─/*─────▶ [ frontend (Next.js  :3000) ]
```

---

## TL;DR

From your **local** machine (with `gcloud` installed and logged in):

```bash
# 1. Provision a VM + firewall rule
./deploy/gcp/provision.sh

# 2. SSH in
gcloud compute ssh brainos-vm --zone=us-central1-a

# 3. On the VM: bootstrap, configure env, start everything
curl -fsSL https://raw.githubusercontent.com/<your-fork>/BrainOS/main/deploy/gcp/bootstrap.sh | bash
cd ~/BrainOS
cp src/python_backend/.env.example src/python_backend/.env
nano src/python_backend/.env            # paste CLAUDE_API_KEY (or set custom endpoint)
docker compose up -d --build

# 4. Open it
echo "http://$(curl -s ifconfig.me)"
```

---

## 1. Prerequisites (local)

- `gcloud` CLI installed and authenticated: `gcloud auth login`
- A GCP project selected: `gcloud config set project <YOUR_PROJECT_ID>`
- Billing enabled on that project

---

## 2. Provision the VM

Edit the top of `provision.sh` if you want a different machine type / zone /
name, then run it:

```bash
./deploy/gcp/provision.sh
```

It will:
1. Create an `e2-standard-2` Ubuntu 22.04 VM named `brainos-vm`
2. Open TCP port 80 with a firewall rule named `brainos-http`
3. Attach a 30 GB persistent disk

Cost: ~$50/mo for the VM. If you self-host the LLM on a GPU VM, expect more.

---

## 3. Bootstrap the VM

SSH in and run the bootstrap script. It installs Docker + the Docker Compose
plugin and clones the repo into `~/BrainOS`.

```bash
gcloud compute ssh brainos-vm --zone=us-central1-a
bash <(curl -fsSL https://raw.githubusercontent.com/<your-fork>/BrainOS/main/deploy/gcp/bootstrap.sh)
```

If you don't want to fetch from the internet, you can also `scp` the repo up
and run `bash deploy/gcp/bootstrap.sh` from inside the cloned directory — it
detects an existing clone and skips that step.

---

## 4. Configure

Two modes — pick one in `src/python_backend/.env`:

### A. Claude API (default — easiest)

```env
LLM_PROVIDER=claude
CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-4-5-20251001
```

### B. Self-hosted model endpoint

Run your model on a separate VM (or the same one, if you have a GPU) behind
any OpenAI-compatible server (vLLM, Ollama, TGI, llama.cpp). Then:

```env
LLM_PROVIDER=custom
LLM_API_BASE=http://<gpu-host>:8000/v1
MODEL_NAME=meta-llama/Llama-3.1-70B-Instruct
```

You can switch between the two by editing `.env` and running
`docker compose restart backend` — no rebuild needed.

---

## 5. Start

```bash
cd ~/BrainOS
docker compose up -d --build
docker compose logs -f         # watch startup
```

Open `http://<vm-external-ip>` in a browser. The first request can be slow
while sentence-transformers downloads embedding weights — subsequent ones are
fast.

---

## Day-2 ops

```bash
# Update to latest code
git pull && docker compose up -d --build

# Tail logs
docker compose logs -f backend
docker compose logs -f frontend

# Restart just one service after editing .env
docker compose restart backend

# Wipe brain state (keeps containers running)
docker compose exec backend curl -s -X DELETE http://localhost:8081/api/clear

# Full teardown (deletes VM + firewall rule, keeps your local repo)
./deploy/gcp/teardown.sh
```

State (the brain.json + chromadb vectors) lives in the `brain_data` Docker
volume on the VM. It survives `docker compose down`, but **not** VM deletion.
For real backups, run `gcloud compute disks snapshot ...` against the VM's
disk on a schedule.

---

## HTTPS

nginx serves both `:80` and `:443`. On first boot it auto-generates a
**self-signed cert** so HTTPS works immediately on the raw IP — browsers
will warn (expected), but the connection is encrypted.

Plain HTTP is redirected to HTTPS.

### Switch to a real Let's Encrypt cert

Once you have a domain, point an A record at the VM's external IP, wait for
DNS to propagate, then run on the VM:

```bash
cd ~/BrainOS
./deploy/gcp/init-tls.sh letsencrypt brainos.example.com you@example.com
```

The script:
1. Verifies the domain resolves to this VM
2. Stops nginx briefly so certbot can bind `:80`
3. Issues a Let's Encrypt cert via `certbot certonly --standalone`
4. Copies it into `./certs/` (which nginx mounts)
5. Restarts nginx

### Renewals

Let's Encrypt certs expire every 90 days. Add a weekly cron entry (the
script prints the exact line at the end):

```cron
0 3 * * 0  cd /home/<you>/BrainOS && ./deploy/gcp/init-tls.sh letsencrypt brainos.example.com you@example.com >>/var/log/brainos-tls.log 2>&1
```

### Regenerate the self-signed cert

```bash
./deploy/gcp/init-tls.sh self-signed
```
