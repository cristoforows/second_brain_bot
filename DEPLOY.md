# Deployment Guide - Second Brain Telegram Bot

Complete deployment guide for containerizing and deploying the Second Brain Telegram Bot using Docker and Kubernetes.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Docker Deployment](#docker-deployment)
3. [Kubernetes Deployment](#kubernetes-deployment)
4. [Cloud Platform Specific Guides](#cloud-platform-specific-guides)
5. [Configuration](#configuration)
6. [Monitoring and Maintenance](#monitoring-and-maintenance)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools

- **Docker** (v20.10+): [Install Docker](https://docs.docker.com/get-docker/)
- **Docker Compose** (v2.0+): Usually included with Docker Desktop
- **Kubernetes** (v1.24+): [kubectl installation](https://kubernetes.io/docs/tasks/tools/)
- **Git**: For cloning the repository

### Required Credentials

Before deployment, gather the following:

1. **Telegram Bot Token**: Get from [@BotFather](https://t.me/botfather)
2. **Google OAuth Credentials**: From [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
   - Client ID
   - Client Secret
   - Redirect URI
3. **Database Credentials**: PostgreSQL connection details
4. **Domain Name**: For webhook and OAuth callbacks (must be HTTPS)
5. **SSL Certificate**: Let's Encrypt or commercial certificate

### Generate Encryption Key

```bash
# Generate Fernet encryption key for token storage
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Docker Deployment

### Option 1: Docker Compose (Recommended for Development/Small Deployments)

#### Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/second_brain_bot.git
cd second_brain_bot
```

#### Step 2: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
nano .env
```

Required environment variables:
```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
WEBHOOK_URL=https://your-domain.com
WEBHOOK_PORT=8443
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-client-secret
GOOGLE_REDIRECT_URI=https://your-domain.com/oauth/callback
DATABASE_USER=dbuser
DATABASE_PASSWORD=securepassword
DATABASE_HOST=your-db-host
DATABASE_PORT=5432
DATABASE_NAME=second_brain
TOKEN_ENCRYPTION_KEY=your-generated-fernet-key
```

#### Step 3: Build and Run

```bash
# Build the image
docker-compose build

# Start the bot
docker-compose up -d

# View logs
docker-compose logs -f telegram-bot

# Check status
docker-compose ps
```

#### Step 4: Set Telegram Webhook

```bash
# Set webhook URL (run once after deployment)
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-domain.com/webhook/<YOUR_BOT_TOKEN>"}'

# Verify webhook
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

#### Step 5: Test Deployment

```bash
# Test health endpoint
curl https://your-domain.com/

# Send test message to bot on Telegram
# Bot should respond with authentication prompt
```

#### Management Commands

```bash
# Stop the bot
docker-compose stop

# Restart the bot
docker-compose restart

# View logs
docker-compose logs -f

# Update to new version
git pull
docker-compose build
docker-compose up -d

# Remove containers
docker-compose down

# Remove containers and volumes
docker-compose down -v
```

### Option 2: Standalone Docker

```bash
# Build image
docker build -t second-brain-bot:latest .

# Run container
docker run -d \
  --name second-brain-bot \
  -p 8443:8443 \
  --env-file .env \
  --restart unless-stopped \
  second-brain-bot:latest

# View logs
docker logs -f second-brain-bot

# Stop container
docker stop second-brain-bot

# Remove container
docker rm second-brain-bot
```

---

## Kubernetes Deployment

### Prerequisites

1. **Kubernetes Cluster**: Running cluster (local, cloud, or managed)
2. **kubectl**: Configured to access your cluster
3. **Container Registry**: Docker Hub, GitHub Container Registry, AWS ECR, etc.
4. **Ingress Controller**: nginx-ingress or AWS ALB Controller
5. **Cert Manager** (optional): For automatic SSL certificates

### Step 1: Build and Push Docker Image

```bash
# Build image
docker build -t your-registry/second-brain-bot:latest .

# Tag image
docker tag second-brain-bot:latest your-registry/second-brain-bot:v1.0.0

# Login to registry
docker login your-registry

# Push image
docker push your-registry/second-brain-bot:latest
docker push your-registry/second-brain-bot:v1.0.0
```

### Step 2: Configure Kubernetes Manifests

#### Update Secret (`k8s/secret.yaml`)

```bash
# Option 1: Edit directly (NOT RECOMMENDED for production)
nano k8s/secret.yaml

# Option 2: Use kubectl to create secret from literals
kubectl create namespace telegram-bot

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

# Option 3: Use sealed-secrets (RECOMMENDED for production)
# Install sealed-secrets controller first
# Then create sealed secret
kubeseal --format=yaml < k8s/secret.yaml > k8s/sealed-secret.yaml
kubectl apply -f k8s/sealed-secret.yaml
```

#### Update ConfigMap (`k8s/configmap.yaml`)

```bash
nano k8s/configmap.yaml
# Update WEBHOOK_URL to your domain
```

#### Update Deployment (`k8s/deployment.yaml`)

```bash
nano k8s/deployment.yaml
# Update image: your-registry/second-brain-bot:latest
```

#### Update Ingress (`k8s/ingress.yaml`)

```bash
nano k8s/ingress.yaml
# Update host: your-domain.com
# Update annotations based on your ingress controller
```

### Step 3: Deploy to Kubernetes

#### Method 1: Direct Apply

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Apply all manifests
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa.yaml

# Or apply all at once
kubectl apply -f k8s/
```

#### Method 2: Using Kustomize (Recommended)

```bash
# Deploy using kustomize
kubectl apply -k k8s/

# Or with specific overlay
kubectl apply -k k8s/overlays/production
```

### Step 4: Verify Deployment

```bash
# Check namespace
kubectl get namespace telegram-bot

# Check all resources
kubectl get all -n telegram-bot

# Check pod status
kubectl get pods -n telegram-bot

# Check logs
kubectl logs -f deployment/telegram-bot -n telegram-bot

# Check service
kubectl get svc -n telegram-bot

# Check ingress
kubectl get ingress -n telegram-bot

# Describe pod (for troubleshooting)
kubectl describe pod -l app=second-brain-bot -n telegram-bot
```

### Step 5: Set Telegram Webhook

```bash
# Get ingress URL
kubectl get ingress -n telegram-bot

# Set webhook
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-domain.com/webhook/<YOUR_BOT_TOKEN>"}'
```

### Step 6: Test Deployment

```bash
# Port forward to test locally (optional)
kubectl port-forward -n telegram-bot svc/telegram-bot-service 8443:8443

# Test health endpoint
curl https://your-domain.com/

# Send test message to bot on Telegram
```

### Management Commands

```bash
# Scale deployment (Note: Keep replicas=1 for webhooks)
kubectl scale deployment telegram-bot -n telegram-bot --replicas=1

# Update deployment (after pushing new image)
kubectl set image deployment/telegram-bot -n telegram-bot \
  bot=your-registry/second-brain-bot:v1.0.1

# Rolling restart
kubectl rollout restart deployment/telegram-bot -n telegram-bot

# Check rollout status
kubectl rollout status deployment/telegram-bot -n telegram-bot

# Rollback to previous version
kubectl rollout undo deployment/telegram-bot -n telegram-bot

# Delete deployment
kubectl delete -f k8s/
# Or
kubectl delete namespace telegram-bot
```

---

## Cloud Platform Specific Guides

### AWS (EKS)

#### Prerequisites
- AWS CLI configured
- eksctl installed
- AWS account with EKS permissions

#### Create EKS Cluster

```bash
# Create cluster
eksctl create cluster \
  --name second-brain-bot-cluster \
  --region us-west-2 \
  --nodegroup-name standard-workers \
  --node-type t3.medium \
  --nodes 2 \
  --nodes-min 1 \
  --nodes-max 3 \
  --managed

# Configure kubectl
aws eks update-kubeconfig --region us-west-2 --name second-brain-bot-cluster
```

#### Install AWS ALB Controller

```bash
# Create IAM policy
curl -o iam_policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.4.7/docs/install/iam_policy.json

aws iam create-policy \
  --policy-name AWSLoadBalancerControllerIAMPolicy \
  --policy-document file://iam_policy.json

# Install controller
helm repo add eks https://aws.github.io/eks-charts
helm repo update

helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=second-brain-bot-cluster \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller
```

#### Use AWS ECR

```bash
# Create ECR repository
aws ecr create-repository --repository-name second-brain-bot

# Login to ECR
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin \
  <account-id>.dkr.ecr.us-west-2.amazonaws.com

# Build and push
docker build -t second-brain-bot .
docker tag second-brain-bot:latest \
  <account-id>.dkr.ecr.us-west-2.amazonaws.com/second-brain-bot:latest
docker push <account-id>.dkr.ecr.us-west-2.amazonaws.com/second-brain-bot:latest
```

#### Configure ALB Ingress

Update `k8s/ingress.yaml` with AWS ALB annotations (see comments in file).

### Google Cloud (GKE)

```bash
# Create GKE cluster
gcloud container clusters create second-brain-bot-cluster \
  --zone us-central1-a \
  --num-nodes 2 \
  --machine-type n1-standard-2

# Configure kubectl
gcloud container clusters get-credentials second-brain-bot-cluster \
  --zone us-central1-a

# Use GCR
docker build -t gcr.io/<project-id>/second-brain-bot:latest .
docker push gcr.io/<project-id>/second-brain-bot:latest
```

### Azure (AKS)

```bash
# Create AKS cluster
az aks create \
  --resource-group myResourceGroup \
  --name second-brain-bot-cluster \
  --node-count 2 \
  --enable-addons monitoring \
  --generate-ssh-keys

# Configure kubectl
az aks get-credentials \
  --resource-group myResourceGroup \
  --name second-brain-bot-cluster

# Use ACR
az acr create --resource-group myResourceGroup --name myregistry --sku Basic
az acr login --name myregistry
docker build -t myregistry.azurecr.io/second-brain-bot:latest .
docker push myregistry.azurecr.io/second-brain-bot:latest
```

### DigitalOcean (DOKS)

```bash
# Create cluster via UI or API

# Configure kubectl
doctl kubernetes cluster kubeconfig save <cluster-id>

# Use DigitalOcean Container Registry
doctl registry create myregistry
doctl registry login
docker build -t registry.digitalocean.com/myregistry/second-brain-bot:latest .
docker push registry.digitalocean.com/myregistry/second-brain-bot:latest
```

---

## Configuration

### SSL/TLS Certificates

#### Option 1: Let's Encrypt (cert-manager)

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.12.0/cert-manager.yaml

# Create ClusterIssuer
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
    - http01:
        ingress:
          class: nginx
EOF

# Ingress will automatically request certificate
```

#### Option 2: Manual Certificate

```bash
# Create TLS secret from certificate files
kubectl create secret tls telegram-bot-tls-cert \
  --namespace=telegram-bot \
  --cert=path/to/cert.crt \
  --key=path/to/cert.key
```

### Database Setup

#### PostgreSQL on Kubernetes

```bash
# Create PostgreSQL deployment
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
  namespace: telegram-bot
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: telegram-bot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15-alpine
        env:
        - name: POSTGRES_DB
          value: second_brain
        - name: POSTGRES_USER
          value: botuser
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: telegram-bot-secrets
              key: DATABASE_PASSWORD
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-storage
        persistentVolumeClaim:
          claimName: postgres-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: telegram-bot
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
EOF
```

### Environment-Specific Configuration

Create overlays for different environments:

```bash
# Directory structure
k8s/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── kustomization.yaml
└── overlays/
    ├── development/
    │   ├── kustomization.yaml
    │   └── patch-replica-count.yaml
    ├── staging/
    │   └── kustomization.yaml
    └── production/
        ├── kustomization.yaml
        └── patch-replica-count.yaml

# Deploy specific environment
kubectl apply -k k8s/overlays/production
```

---

## Monitoring and Maintenance

### Logging

#### View Logs

```bash
# Docker Compose
docker-compose logs -f telegram-bot

# Kubernetes
kubectl logs -f deployment/telegram-bot -n telegram-bot

# Specific pod
kubectl logs <pod-name> -n telegram-bot

# Previous crashed container
kubectl logs <pod-name> -n telegram-bot --previous
```

#### Centralized Logging (ELK/EFK Stack)

```bash
# Install Elasticsearch, Fluentd, Kibana
kubectl apply -f https://raw.githubusercontent.com/elastic/cloud-on-k8s/2.7/config/crds.yaml
kubectl apply -f https://raw.githubusercontent.com/elastic/cloud-on-k8s/2.7/config/operator.yaml
```

### Monitoring

#### Prometheus + Grafana

```bash
# Install Prometheus Operator
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace

# Access Grafana
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80
# Username: admin, Password: prom-operator
```

### Health Checks

```bash
# Check application health
curl https://your-domain.com/

# Check Telegram webhook
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Kubernetes health
kubectl get pods -n telegram-bot
kubectl describe pod <pod-name> -n telegram-bot
```

### Backups

#### Database Backup

```bash
# PostgreSQL backup
kubectl exec -n telegram-bot postgres-pod -- \
  pg_dump -U botuser second_brain > backup.sql

# Restore
kubectl exec -i -n telegram-bot postgres-pod -- \
  psql -U botuser second_brain < backup.sql
```

### Updates and Rollbacks

```bash
# Update image
kubectl set image deployment/telegram-bot -n telegram-bot \
  bot=your-registry/second-brain-bot:v1.0.1

# Check rollout
kubectl rollout status deployment/telegram-bot -n telegram-bot

# Rollback
kubectl rollout undo deployment/telegram-bot -n telegram-bot

# Rollback to specific revision
kubectl rollout history deployment/telegram-bot -n telegram-bot
kubectl rollout undo deployment/telegram-bot -n telegram-bot --to-revision=2
```

---

## Troubleshooting

### Common Issues

#### 1. Bot Not Responding

```bash
# Check pod status
kubectl get pods -n telegram-bot

# Check logs
kubectl logs -f deployment/telegram-bot -n telegram-bot

# Check webhook info
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Reset webhook
curl -X POST "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d '{"url": "https://your-domain.com/webhook/<TOKEN>"}'
```

#### 2. Connection Refused / 502 Bad Gateway

```bash
# Check service
kubectl get svc -n telegram-bot
kubectl describe svc telegram-bot-service -n telegram-bot

# Check ingress
kubectl get ingress -n telegram-bot
kubectl describe ingress telegram-bot-ingress -n telegram-bot

# Check endpoints
kubectl get endpoints -n telegram-bot
```

#### 3. Database Connection Issues

```bash
# Check database pod
kubectl get pods -n telegram-bot | grep postgres

# Test connection from bot pod
kubectl exec -it <bot-pod> -n telegram-bot -- \
  python -c "import psycopg2; conn = psycopg2.connect('dbname=second_brain user=botuser host=postgres password=<pass>'); print('Connected')"
```

#### 4. SSL/TLS Certificate Issues

```bash
# Check certificate
kubectl get certificate -n telegram-bot

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Describe certificate
kubectl describe certificate telegram-bot-tls-cert -n telegram-bot
```

#### 5. Image Pull Errors

```bash
# Check image pull secret
kubectl get secret -n telegram-bot

# Create image pull secret
kubectl create secret docker-registry regcred \
  --docker-server=<registry> \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> \
  -n telegram-bot

# Add to deployment
kubectl patch serviceaccount default -n telegram-bot \
  -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```

### Debug Mode

Enable debug logging:

```bash
# Update ConfigMap
kubectl edit configmap telegram-bot-config -n telegram-bot
# Set LOG_LEVEL: DEBUG

# Restart pods
kubectl rollout restart deployment/telegram-bot -n telegram-bot
```

### Performance Issues

```bash
# Check resource usage
kubectl top pods -n telegram-bot
kubectl top nodes

# Increase resources
kubectl edit deployment telegram-bot -n telegram-bot
# Adjust resources.requests and resources.limits
```

### Getting Help

- Check logs: `kubectl logs -f deployment/telegram-bot -n telegram-bot`
- Check events: `kubectl get events -n telegram-bot --sort-by='.lastTimestamp'`
- Describe resources: `kubectl describe <resource> <name> -n telegram-bot`
- Shell into pod: `kubectl exec -it <pod-name> -n telegram-bot -- /bin/sh`

---

## Security Best Practices

1. **Never commit secrets**: Use sealed-secrets or external secret managers
2. **Use private container registry**: Protect your images
3. **Enable RBAC**: Restrict pod permissions
4. **Regular updates**: Keep dependencies and base images updated
5. **Network policies**: Restrict pod-to-pod communication
6. **Resource limits**: Prevent resource exhaustion
7. **Security scanning**: Scan images for vulnerabilities
8. **Audit logs**: Enable Kubernetes audit logging
9. **Backup regularly**: Automate database backups
10. **Monitor**: Set up alerts for errors and anomalies

---

## Production Checklist

- [ ] SSL/TLS certificates configured
- [ ] Secrets stored securely (not in Git)
- [ ] Database backups automated
- [ ] Monitoring and alerting configured
- [ ] Resource limits set appropriately
- [ ] Health checks configured
- [ ] Ingress/Load balancer configured
- [ ] Domain DNS configured
- [ ] Telegram webhook verified
- [ ] Google OAuth callback working
- [ ] Logs aggregation configured
- [ ] Disaster recovery plan documented
- [ ] Security scanning enabled
- [ ] Update strategy defined
- [ ] Documentation updated

---

## Additional Resources

- [Kubernetes Documentation](https://kubernetes.io/docs/)
- [Docker Documentation](https://docs.docker.com/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Google Drive API](https://developers.google.com/drive/api/v3/about-sdk)
- [nginx Ingress Controller](https://kubernetes.github.io/ingress-nginx/)
- [cert-manager](https://cert-manager.io/docs/)

---

## Support

For issues or questions:
1. Check the [troubleshooting section](#troubleshooting)
2. Review application logs
3. Check Kubernetes events
4. Open an issue on GitHub

---

**Last Updated**: 2024-02-14
**Version**: 1.0.0
