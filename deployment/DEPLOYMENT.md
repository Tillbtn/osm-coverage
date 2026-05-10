# Deployment Guide

This guide explains how to deploy the OSM Coverage Site on a Proxmox LXC.

## Prerequisites
- **Server**: Proxmox LXC (Debian/Ubuntu).
- **Resources**: 7.5GB+ RAM, 24GB+ Disk.
- **Docker** & **Docker Compose** installed.

## 1. Setup
Clone the repository

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

## 3. Set up cronjob for updates

Add the following line to your crontab:

```bash
0 * * * * cd /opt/osm-coverage/deployment && docker compose run --rm worker
```

## 4. Update
To update the site with the latest updates:

```bash
docker compose -f deployment/docker-compose.yml up -d --build
```
