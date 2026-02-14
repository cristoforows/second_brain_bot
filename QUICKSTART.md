# Quick Start Guide - Docker & Kubernetes Deployment

## What Was Created

Your repository is now Docker and Kubernetes ready! Here's what was added:

### Docker Files
- `Dockerfile` - Multi-stage build for optimized container image
- `.dockerignore` - Excludes unnecessary files from Docker build
- `docker-compose.yml` - Local development setup with Docker Compose

### Kubernetes Manifests (`k8s/` directory)
- `namespace.yaml` - Isolated namespace for the bot
- `configmap.yaml` - Non-sensitive configuration
- `secret.yaml` - Sensitive credentials (template)
- `deployment.yaml` - Main application deployment
- `service.yaml` - Internal service definition
- `ingress.yaml` - External routing/SSL termination
- `hpa.yaml` - Horizontal Pod Autoscaler (optional)
- `pvc.yaml` - Persistent storage (optional)
- `kustomization.yaml` - Kustomize configuration
- `README.md` - Kubernetes-specific documentation

### CI/CD
- `.github/workflows/docker-build.yml` - Automated Docker image builds

### Documentation
- `DEPLOY.md` - Comprehensive deployment manual (200+ lines)
- `QUICKSTART.md` - This file

---

## 🚀 Quick Start - Docker Compose (5 minutes)

Perfect for local testing or small deployments.

### Step 1: Configure Environment

```bash
# Make sure .env file exists with your credentials
cat .env.example > .env
nano .env  # Fill in your actual values
```

### Step 2: Build and Run

```bash
# Build the Docker image
docker-compose build

# Start the bot (runs in background)
docker-compose up -d

# View logs
docker-compose logs -f telegram-bot
```

### Step 3: Set Telegram Webhook

```bash
# Replace <YOUR_BOT_TOKEN> with your actual token
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-domain.com/webhook/<YOUR_BOT_TOKEN>"}'
```

### Step 4: Test

Send a message to your bot on Telegram - it should respond!

### Management

```bash
# Stop the bot
docker-compose stop

# Restart
docker-compose restart

# View logs
docker-compose logs -f

# Stop and remove
docker-compose down
```

---

## ☸️ Quick Start - Kubernetes (15 minutes)

For production deployments on any Kubernetes cluster.

### Prerequisites

- Kubernetes cluster running
- `kubectl` configured
- Container registry (Docker Hub, GitHub Container Registry, etc.)
- Domain name with SSL certificate

### Step 1: Build and Push Image

```bash
# Build image
docker build -t your-username/second-brain-bot:latest .

# Login to registry
docker login  # or: docker login ghcr.io

# Push image
docker push your-username/second-brain-bot:latest
```

### Step 2: Configure Kubernetes Manifests

Update these files:

**k8s/deployment.yaml**
```yaml
# Line 54: Change image to your registry
image: your-username/second-brain-bot:latest
```

**k8s/configmap.yaml**
```yaml
# Update WEBHOOK_URL to your domain
WEBHOOK_URL: "https://your-domain.com"
```

**k8s/ingress.yaml**
```yaml
# Update host to your domain
host: your-domain.com
```

**k8s/secret.yaml** - DO NOT COMMIT with real values!
```bash
# Option 1: Create secret via kubectl (recommended)
kubectl create namespace telegram-bot

kubectl create secret generic telegram-bot-secrets \
  --namespace=telegram-bot \
  --from-literal=TELEGRAM_BOT_TOKEN='your-bot-token' \
  --from-literal=GOOGLE_CLIENT_ID='your-client-id' \
  --from-literal=GOOGLE_CLIENT_SECRET='your-secret' \
  --from-literal=GOOGLE_REDIRECT_URI='https://your-domain.com/oauth/callback' \
  --from-literal=DATABASE_USER='dbuser' \
  --from-literal=DATABASE_PASSWORD='dbpass' \
  --from-literal=DATABASE_HOST='your-db-host' \
  --from-literal=DATABASE_PORT='5432' \
  --from-literal=DATABASE_NAME='second_brain' \
  --from-literal=TOKEN_ENCRYPTION_KEY='your-fernet-key'

# Then remove k8s/secret.yaml from deployment (skip it)
```

### Step 3: Deploy to Kubernetes

```bash
# Apply all manifests (skip secret.yaml if created via kubectl)
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
# kubectl apply -f k8s/secret.yaml  # Skip if created via kubectl
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml

# Or use kustomize (make sure to skip secret.yaml)
kubectl apply -k k8s/
```

### Step 4: Verify Deployment

```bash
# Check all resources
kubectl get all -n telegram-bot

# Check pod logs
kubectl logs -f deployment/telegram-bot -n telegram-bot

# Check ingress (wait for external IP)
kubectl get ingress -n telegram-bot
```

### Step 5: Set Telegram Webhook

```bash
# After ingress has external IP/domain
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-domain.com/webhook/<YOUR_BOT_TOKEN>"}'
```

### Step 6: Test

Send a message to your bot on Telegram!

---

## 🔧 Troubleshooting

### Bot Not Responding

```bash
# Docker Compose
docker-compose logs telegram-bot

# Kubernetes
kubectl logs -f deployment/telegram-bot -n telegram-bot

# Check webhook status
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

### Can't Access Bot (502/404 errors)

```bash
# Check if service is running
kubectl get pods -n telegram-bot
kubectl get svc -n telegram-bot
kubectl get ingress -n telegram-bot

# Check ingress logs (nginx example)
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller
```

### Image Pull Errors

```bash
# Check if image exists
docker pull your-username/second-brain-bot:latest

# Create image pull secret
kubectl create secret docker-registry regcred \
  --docker-server=docker.io \
  --docker-username=your-username \
  --docker-password=your-password \
  --namespace=telegram-bot

# Update deployment to use secret
# Add to k8s/deployment.yaml under spec.template.spec:
# imagePullSecrets:
# - name: regcred
```

---

## 📊 What's Next?

1. **Read DEPLOY.md** - Comprehensive guide with cloud-specific instructions
2. **Set up monitoring** - Prometheus, Grafana, or cloud-native monitoring
3. **Configure backups** - Database backup automation
4. **Set up CI/CD** - Automate deployments with GitHub Actions
5. **Security hardening** - Use sealed-secrets, network policies, RBAC
6. **Scale if needed** - Adjust resources in deployment.yaml

---

## 🎯 Deployment Options

### Local Development
```bash
docker-compose up -d
```

### Single Server (VPS)
```bash
docker-compose up -d
# or
docker run -d --env-file .env -p 8443:8443 second-brain-bot
```

### Kubernetes (Any Cloud)
```bash
kubectl apply -k k8s/
```

### Cloud-Specific

**AWS (EKS)**
- See DEPLOY.md section "AWS (EKS)"
- Use ECR for container registry
- Use ALB Ingress Controller

**Google Cloud (GKE)**
- See DEPLOY.md section "Google Cloud (GKE)"
- Use GCR/Artifact Registry
- Use GCP Load Balancer

**Azure (AKS)**
- See DEPLOY.md section "Azure (AKS)"
- Use ACR for container registry
- Use Azure Application Gateway

**DigitalOcean (DOKS)**
- See DEPLOY.md section "DigitalOcean (DOKS)"
- Use DO Container Registry
- Use DO Load Balancer

---

## 📚 Documentation

- `DEPLOY.md` - Full deployment guide (200+ lines)
- `k8s/README.md` - Kubernetes-specific docs
- `README.md` - Project README
- `DEVELOPMENT.md` - Development setup

---

## 🔒 Security Reminder

⚠️ **NEVER commit secrets to Git!**

- Use `kubectl create secret` for Kubernetes
- Use environment variables for Docker
- Use secret managers (AWS Secrets Manager, Vault, etc.)
- Use sealed-secrets or external-secrets-operator
- Keep `.env` in `.gitignore`

---

## 🆘 Need Help?

1. Check logs: `docker-compose logs -f` or `kubectl logs -f deployment/telegram-bot -n telegram-bot`
2. Read DEPLOY.md for detailed troubleshooting
3. Check k8s/README.md for Kubernetes-specific issues
4. Verify webhook: `curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"`

---

**Happy Deploying! 🚀**
