#!/bin/bash

TSTAMP=`date +%Y%m%d-%H%M%S`
LOGFILE="/var/log/winbind-$TSTAMP.log"
exec > >(tee -i $LOGFILE)
exec 2>&1

# Turn on command tracing
set -xe

# Install rpms
pkgs=`ls rpms/*.rpm 2>/dev/null | tr '\n' ' '`
sudo rpm -Uh --replacepkgs --replacefiles --nosignature $pkgs

# Manage services
sudo systemctl start winbind
sudo systemctl enable winbind

sudo alternatives --set cifs-idmap-plugin /usr/lib64/cifs-utils/idmapwb.so

sudo systemctl stop sssd
sudo systemctl disable sssd

# Remove
yum remove -y sssd-libwbclient

# Restart stronglink services
sudo systemctl restart smb control-panel slink-star
