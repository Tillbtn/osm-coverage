# Deployment Guide for Proxmox (Docker)

This guide explains how to deploy the OSM Coverage Site on a Proxmox server using Docker.

## Prerequisites

1.  **Proxmox Server** with an LXC container or VM running Debian/Ubuntu.
2.  **Docker & Docker Compose** installed on that container/VM.
    - [Official Install Guide](https://docs.docker.com/engine/install/ubuntu/)

## Installation Steps

1.  **Prepare Frontend**
    On your local machine (or wherever you have Node.js installed), build the frontend:
    ```bash
    cd site
    npm install
    npm run build
    # This creates a 'dist' folder
    cd ..
    ```

2.  **Copy Files**
    Transfer the following files/folders to your server:
    - `Dockerfile`
    - `docker-compose.yml`
    - `nginx.conf`
    - `run_updates.sh`
    - `requirements.txt`
    - `scripts/`
    - `site/dist/` (The built frontend)
    - `site/public/` (Initial data/history, required for persistence)

    ```bash
    # Example using SCP
    # Ensure the destination directories exist first:
    ssh root@192.168.178.57 "mkdir -p /root/nds-addresses/site"
    
    # Now copy files
    # Copy 'dist' INTO 'site' -> /root/nds-addresses/site/dist
    scp -r site/dist root@192.168.178.57:/root/nds-addresses/site/
    
    # Copy 'public' INTO 'site' -> /root/nds-addresses/site/public
    scp -r site/public root@192.168.178.57:/root/nds-addresses/site/
    
    # Copy scripts to root folder
    scp -r scripts root@192.168.178.57:/root/nds-addresses/
    
    # Copy config files
    scp Dockerfile docker-compose.yml nginx.conf run_updates.sh requirements.txt root@192.168.178.57:/root/nds-addresses/
    ```

3.  **Start Services**
    Navigate to the directory and start the containers:
    ```bash
    cd /root/nds-addresses
    # Ensure site/public exists and has permissions
    mkdir -p site/public/districts
    


### Nginx 403 Forbidden
If you see a `403 Forbidden` error when accessing the site:
This usually means Nginx cannot read the files due to **permissions** or the directory is empty.

1.  **Check Permissions**:
    Run this on the Proxmox Host (or inside the container via SSH) to fix permissions:
    ```bash
    chmod -R 755 /root/nds-addresses/site
    ```
    This ensures everyone (including the Nginx user inside the container) can read the files.

2.  **Verify Files Exist**:
    Check if the files actually arrived:
    ```bash
    ls -F /root/nds-addresses/site/dist/
    ```
    It should show `index.html`, `assets/`, etc. If it's empty, the `scp` might have failed or put them in the wrong place (e.g., `site/dist/dist`).


3.  **Verify**
    - The **web** container serves the site on `http://your-server-ip:8080`.
    - The **worker** container runs in the background. Check logs:
      ```bash
      docker compose logs -f worker
      ```

## Architecture

- **Web Service (`nginx`)**:
    - Serves static files from `./site`.
    - Configured in `nginx.conf`.
    - Auto-restarts on failure.

- **Worker Service (`python`)**:
    - Builds custom image from `Dockerfile`.
    - Runs `run_updates.sh` entrypoint.
    - Executes the data pipeline (ALKIS download -> OSM fetch -> Compare -> MVT generation).
    - Sleeps for 24 hours between runs.
    - Mounts `./data` and `./site` so generated files are immediately visible to Nginx.

## Maintenance

- **Force Manual Update**:
  Restart the worker container to trigger an immediate run:
  ```bash
  docker compose restart worker
  ```
  docker compose down
  ```

## Troubleshooting

### SSH Permission Denied
If you get "Permission denied" when trying to SCP to the container:
1.  **Open Proxmox Console**: Go to the Proxmox Web UI, select the container (121), and click "Console".
2.  **Enable Root Login**:
    Edit the SSH config:
    ```bash
    nano /etc/ssh/sshd_config
    ```
    Find the line `#PermitRootLogin prohibit-password` (or similar) and change it to:
    ```
    PermitRootLogin yes
    ```
    (Make sure to remove the `#` at the start).
3.  **Restart SSH**:
    ```bash
    systemctl restart ssh
    ```
4.  **Set Password**:
    Ensure the root user has a password set:
    ```bash
    passwd
    ```

### Docker OCI / Permission Denied Error
If you see an error like: `failed to create shim task: OCI runtime create failed ... open sysctl net.ipv4.ip_unprivileged_port_start ... permission denied`:

This usually requires **Nesting** and **Keyctl** to be enabled in Proxmox.

1.  **Stop the Container**: In Proxmox, stop container 121.
2.  **Enable Features**:
    - Go to **Options** -> **Features**.
    - Double click (or click Edit).
    - Check the box for **Nesting**.
    - Check the box for **Keyctl** (sometimes required for Docker signatures/keys).
    - Click OK.
3.  **Start the Container**: Start container 121 again.
4.  **Retry Deployment**.

**Solution 1 (Best): Update Proxmox**
This is a known bug in older `lxc-pve` versions (AppArmor incorrectly blocks `/proc/sys` access).
On your **Proxmox Host** (Shell into the main node, NOT the container), run:
```bash
apt update && apt install lxc-pve
```
Ensure you are on version `6.0.5-2` or newer. Then restart the container.

**Solution 2: Workarounds (If you cannot update)**
It might be an issue with "Unprivileged" containers. You can try:
-   **Method A**: In the Features menu, ensure **keyctl=1** is set.
-   **Method B**: Edit the LXC config on the Proxmox **HOST**:
    `/etc/pve/lxc/121.conf`
    Add:
    ```
    lxc.apparmor.profile: unconfined
    lxc.cgroup.devices.allow: a
    lxc.cap.drop:
    ```
    (This disables AppArmor protections for this container).

**Alternative for `net.ipv4.ip_unprivileged_port_start`**:
This specific error happens when Docker tries to allow ports < 1024.
-   You are already root in the container, but it's a "fake" root.
-   Try upgrading the packages in the container: `apt update && apt upgrade`.
-   Try re-installing Docker if it was installed via snap (use `apt` / official script instead).


