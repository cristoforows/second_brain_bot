# Kubernetes Manifests for Second Brain Bot

This directory contains Kubernetes manifests for deploying the Second Brain Telegram Bot.

## Directory Structure

```
k8s/
├── namespace.yaml        # Namespace definition
├── configmap.yaml       # Configuration (non-sensitive)
├── secret.yaml          # Secrets (⚠️ DO NOT COMMIT with real values)
├── deployment.yaml      # Main application deployment
├── service.yaml         # Service definition
├── ingress.yaml        # Ingress/routing rules
├── hpa.yaml            # Horizontal Pod Autoscaler
├── pvc.yaml            # Persistent Volume Claim (optional)
└── kustomization.yaml  # Kustomize configuration
```

## Quick Start

### 1. Update Configuration

Before deploying, update these files:

**secret.yaml** - Add your credentials:
```bash
# IMPORTANT: Never commit real secrets to Git!
# Use one of these methods:
# - kubectl create secret (command line)
# - Sealed Secrets (encrypted secrets in Git)
# - External Secrets Operator (fetch from vault)
```

**configmap.yaml** - Update:
- `WEBHOOK_URL`: Your public domain
- `WEBHOOK_PATH`: Webhook path prefix (default: `/webhook`)
- `DRIVE_FOLDER_NAME`: Markdown filename in Drive (default: `second_brain_inbox.md`)

**deployment.yaml** - Update:
- `image`: Your container registry and image

**ingress.yaml** - Update:
- `host`: Your domain name
- Annotations for your ingress controller

### 2. Deploy

```bash
# Method 1: Apply all manifests
kubectl apply -f k8s/

# Method 2: Use kustomize
kubectl apply -k k8s/

# Method 3: Apply in order
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
```

### 3. Verify

```bash
# Check all resources
kubectl get all -n telegram-bot

# Check logs
kubectl logs -f deployment/telegram-bot -n telegram-bot

# Check ingress
kubectl get ingress -n telegram-bot
```

## Security Recommendations

### DO NOT commit secrets to Git!

Use one of these secure methods:

#### Option 1: Create secrets via kubectl

```bash
kubectl create secret generic telegram-bot-secrets \
  --namespace=telegram-bot \
  --from-literal=TELEGRAM_BOT_TOKEN='your-token' \
  --from-literal=GOOGLE_CLIENT_ID='your-client-id' \
  --from-literal=GOOGLE_CLIENT_SECRET='your-secret' \
  --from-literal=GOOGLE_REDIRECT_URI='https://your-domain.com/oauth/callback' \
  --from-literal=DATABASE_USER='dbuser' \
  --from-literal=DATABASE_PASSWORD='dbpass' \
  --from-literal=DATABASE_HOST='db-host' \
  --from-literal=DATABASE_PORT='5432' \
  --from-literal=DATABASE_NAME='second_brain' \
  --from-literal=TOKEN_ENCRYPTION_KEY='your-fernet-key'
```

#### Option 2: Sealed Secrets

```bash
# Install sealed-secrets controller
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.24.0/controller.yaml

# Encrypt secret
kubeseal --format=yaml < secret.yaml > sealed-secret.yaml

# Commit sealed-secret.yaml (safe to commit)
kubectl apply -f sealed-secret.yaml
```

#### Option 3: External Secrets Operator

```bash
# Install ESO
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets -n external-secrets-system --create-namespace

# Configure secret store (AWS Secrets Manager, Vault, etc.)
# See: https://external-secrets.io/
```

## Environment-Specific Deployments

Use Kustomize overlays for different environments:

```
k8s/
├── base/
│   └── ... (base manifests)
└── overlays/
    ├── development/
    ├── staging/
    └── production/
```

Deploy with:
```bash
kubectl apply -k k8s/overlays/production
```

## Troubleshooting

```bash
# Check pod status
kubectl get pods -n telegram-bot

# View logs
kubectl logs -f deployment/telegram-bot -n telegram-bot

# Describe pod (see events)
kubectl describe pod <pod-name> -n telegram-bot

# Check ingress
kubectl describe ingress telegram-bot-ingress -n telegram-bot

# Shell into pod
kubectl exec -it <pod-name> -n telegram-bot -- /bin/sh
```

## Cleanup

```bash
# Delete all resources
kubectl delete -f k8s/

# Or delete namespace (removes everything)
kubectl delete namespace telegram-bot
```

## More Information

See [DEPLOY.md](../DEPLOY.md) for comprehensive deployment guide.
