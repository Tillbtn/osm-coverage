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

## 4. Optional: Geofabrik's internal download server

The pipeline downloads OSM extracts from the public Geofabrik server, whose
exports are occasionally delayed. The internal server
(`osm-internal.download.geofabrik.de`) publishes the same extracts earlier and
under less load, but only to logged-in OpenStreetMap accounts.

```bash
cp deployment/.env.example deployment/.env
chmod 600 deployment/.env
$EDITOR deployment/.env        # GEOFABRIK_OSM_USER / GEOFABRIK_OSM_PASSWORD
```

Compose reads `deployment/.env` automatically for the cronjob above (it runs
from `deployment/`). Verify the credentials before the next cron run:

```bash
docker compose run --rm --entrypoint python worker scripts/geofabrik_auth.py --test
```

That logs in, caches the cookie in `data/.geofabrik_cookie` (mode 600, reused
until it expires) and does one authenticated request. During updates each
download logs which server it came from.

Everything here is optional: without credentials, with an expired cookie, or
when the OSM login form changes, the worker logs the reason and downloads from
the public server. To go back, delete `deployment/.env`.

## 5. Update
To update the site with the latest updates:

```bash
docker compose -f deployment/docker-compose.yml up -d --build
```
