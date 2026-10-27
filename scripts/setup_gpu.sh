#!/bin/sh
# NVIDIA's official apt repository; run explicitly as root in the pilot WSL distro.
set -eu
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey -o /tmp/gs-nvidia-key
gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg /tmp/gs-nvidia-key
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list -o /tmp/gs-nvidia-list
sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' /tmp/gs-nvidia-list > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update
apt-get install -y nvidia-container-toolkit
if [ -f /etc/docker/daemon.json ]; then cp -n /etc/docker/daemon.json /etc/docker/daemon.json.goldenstock-backup; fi
nvidia-ctk runtime configure --runtime=docker
service docker restart
exit 0
