# CI/CD Setup

## Overview

This repository uses GitHub Actions for automated testing, building, and deployment.

## Workflows

### CI (Continuous Integration)
**Trigger**: Every push to any branch, PRs to main/develop

**Jobs**:
- **Lint**: Code quality check with Ruff
- **Build**: Docker image build verification

### CD (Continuous Deployment)
**Trigger**: Push to `main` branch

**Jobs**:
- Pull latest code on server
- Build Docker image
- Run database migrations
- Deploy with zero-downtime
- Health check verification

## Setup Instructions

### 1. GitHub Secrets Configuration

Add the following secrets in GitHub repository settings (`Settings` → `Secrets and variables` → `Actions`):

```
SSH_PRIVATE_KEY - SSH private key for deployment server access
```

To generate and add SSH key:

```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy_key

# Copy the private key
cat ~/.ssh/github_deploy_key

# Add public key to server
ssh-copy-id -i ~/.ssh/github_deploy_key.pub -p 29022 ubuntu@195.93.152.69
```

Then add the private key content to GitHub Secrets as `SSH_PRIVATE_KEY`.

### 2. Server Requirements

The deployment server must have:
- Docker and docker-compose installed
- Git repository cloned at `~/azv_motors_backend_v2`
- SSH access on port 29022
- `.env` file configured

### 3. Manual Deployment

To deploy manually from the server:

```bash
cd ~/azv_motors_backend_v2
./scripts/deploy.sh
```

## Deployment Process

1. **Backup**: Database backup created before deployment
2. **Pull**: Latest code pulled from `main` branch
3. **Build**: Docker image rebuilt
4. **Migrate**: Database migrations applied
5. **Deploy**: Services restarted with new image
6. **Verify**: Health check performed

## Rollback

If deployment fails, the script automatically:
- Stops the new containers
- Provides backup location for manual restore

Manual rollback:

```bash
cd ~/azv_motors_backend_v2
docker-compose down
git reset --hard <previous-commit-hash>
docker-compose up -d
```

## Monitoring

Check deployment status:
```bash
docker-compose ps
docker-compose logs -f back
```

## Health Check

API documentation: `http://195.93.152.69:7138/docs`

## Troubleshooting

**Deployment fails at migration step**:
```bash
docker-compose run --rm back alembic current
docker-compose run --rm back alembic history
```

**Container won't start**:
```bash
docker-compose logs back
docker-compose down
docker system prune -f
docker-compose up -d
```

**Database connection issues**:
```bash
docker-compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB
```
