# Deployment Guide (Git)

This guide explains how to deploy the OSM Coverage Site using Git.

## Prerequisites
- **Server**: Proxmox LXC (Debian/Ubuntu).
- **Resources**: 4GB+ RAM, 20GB+ Disk.
- **Git** installed on server.
- **Docker** & **Docker Compose** installed.

## 1. Setup
SSH into your server and clone the repository:

```bash
cd /opt
git clone <YOUR_REPO_URL> osm-coverage
cd osm-coverage
```

## 2. Deploy
Run Docker Compose pointing to the file in `deployment/`:

```bash
# Run from the repository root (/opt/osm-coverage)
docker compose -f deployment/docker-compose.yml up -d --build
```

- **Frontend**: `http://<server-ip>:8080`
- **Data storage**: `data/` folder in the repo root.
- **Logs**: `logs/` folder in the repo root.
- **Backups**: `backups/` folder in the repo root.

## 3. Updates
To update the site with new code:

```bash
cd /opt/osm-coverage
git pull
docker compose -f deployment/docker-compose.yml up -d --build
```
