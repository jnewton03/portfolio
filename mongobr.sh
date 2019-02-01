#!/usr/bin/env bash

# This script will backup and restore a mongo db

set -e

# Variables
ACTION=""
SHARD1=1
SHARD2=1
SHARD3=1
CONFIG=1
CONSTELLATION=0

# Functions
function show_help {
    echo "Usage: mongobr.sh [<args>]"
    echo "  -h\-?        Show help"
    echo "  -a           Action to perform e.g -a backup | -a restore"
    echo "  -o           Backup store path e.g -o /tmp/dump"
    echo "  -s           Backup or Restore will be performed in a star. Default is constellation"
    echo "  -1           Restore only shard 1 db"
    echo "  -2           Restore only shard 2 db"
    echo "  -3           Restore only shard 3 db"
    echo "  -c           Restore only config db"
    echo "  -x           Restore all shards and config dbs"
}

function start_balancer {
    echo "=> Start mongo balancer"
    mongo --port 27017 --quiet --eval "sh.setBalancerState(true)"
}

function stop_balancer {
    echo "=> Stop mongo balancer"
    mongo --port 27017 --quiet --eval "sh.stopBalancer()"
}

function restore_star {
    echo "=> Restore star mongo db"
    mongorestore --quiet --gzip $OUTPUT/
}

function restore_shard {
    shard_to_restore=$1
    shard_name=$2
    shard_host=$3
    echo "=> Restore shard: $shard_host"
    mongorestore --gzip --oplogReplay --host $shard_host $OUTPUT/$shard_name
}

function restore_config {
    config=$1
    echo "=> Restore config: $config"
    # BUG: Failed: config.version: error dropping collection: cannot drop config.version document while in --configsvr mode
    # https://jira.mongodb.org/browse/SERVER-28796.
    mongorestore --drop --gzip --nsExclude=config.version --host $config $OUTPUT/config
    #mongorestore --gzip --host $config $OUTPUT/config
}

function backup_star {
    echo "=> Create backup"
    mongodump --gzip -o $OUTPUT/
}

function backup_constellation {

    echo "=> Get shard 1 host"
    shard1=$(mongo --port 27017 --quiet --eval "db.adminCommand({ listShards: 1 }).shards[0]['host']")
    echo "=> Shard 1: $shard1"
    echo "=> Create shard 1 backup"
    mongodump --host $shard1 --oplog --gzip -o $OUTPUT/shard1

    echo "=> Get shard 2 host"
    shard2=$(mongo --port 27017 --quiet --eval "db.adminCommand({ listShards: 1 }).shards[1]['host']")
    echo "=> Shard 2: $shard2"
    echo "=> Create shard 2 backup"
    mongodump --host $shard2 --oplog --gzip -o $OUTPUT/shard2

    echo "=> Get shard 3 host"
    shard3=$(mongo --port 27017 --quiet --eval "db.adminCommand({ listShards: 1 }).shards[2]['host']")
    echo "=> Shard 3: $shard3"
    echo "=> Create shard 3 backup"
    mongodump --host $shard3 --oplog --gzip -o $OUTPUT/shard3

    echo "=> Get config host"
    config=$(mongo --port 27017 --quiet --eval "db.serverStatus().sharding.configsvrConnectionString")
    echo "=> Config: $config"
    mongodump --host $config --oplog --gzip -o $OUTPUT/config
}

# Arguments
while getopts "h?x123ca:o:" opt; do
    case "$opt" in
    h|\?)
        show_help
        exit 0
        ;;
    a)
        ACTION=$OPTARG
        ;;
    o)
        OUTPUT=$OPTARG
        ;;
    1)
        SHARD1=0
        ;;
    2)
        SHARD2=0
        ;;
    3)
        SHARD3=0
        ;;
    c)
        CONFIG=0
        ;;
    s) 
        CONSTELLATION=1
        ;;
    x) 
        SHARD1=0
        SHARD2=0
        SHARD3=0
        CONFIG=0
        ;;
    esac
done

# Validations
if [[ "$ACTION" != "backup" ]] && [[ "$ACTION" != "restore" ]]; then
    echo "=> Error: -a argument is not valid. It must be -a backup or -a restore"
    exit 1
fi

if [ ! -d "$OUTPUT" ]; then
    echo "=> Error: Invalid directory used with -o"
    exit 1
fi

# Check if this is run as root
if [[ $(id -u) -ne 0 ]]; then
    echo "=> Error: Script must be executed as root"
    exit 1
fi

# Print information
echo "=> Stronglink Version: $(cat /usr/local/radium/etc/VERSION)"
echo "=> Backup Output: $OUTPUT"

# Run backup action
if [[ $ACTION == "backup" ]]; then

    if [ $CONSTELLATION -eq 0 ]; then
        echo "=> Start constellation backup"
        # stop_balancer
        backup_constellation
        # start_balancer
    else
        echo "=> Start star backup"
        backup_star
    fi

elif [[ $ACTION == "restore" ]]; then

    if [ $CONSTELLATION -eq 0 ]; then
        echo "=> Start constellation restore"

        host1=$(mongo --port 27017 --quiet --eval "db.adminCommand({ listShards: 1 }).shards[0]['host']")
        host2=$(mongo --port 27017 --quiet --eval "db.adminCommand({ listShards: 1 }).shards[1]['host']")
        host3=$(mongo --port 27017 --quiet --eval "db.adminCommand({ listShards: 1 }).shards[2]['host']")
        config=$(mongo --port 27017 --quiet --eval "db.serverStatus().sharding.configsvrConnectionString")

        systemctl stop mongos
        
        if [ $SHARD1 -eq 0 ]; then
            restore_shard 0 "shard1" $host1
        fi

        if [ $SHARD2 -eq 0 ]; then
            restore_shard 1 "shard2" $host2
        fi

        if [ $SHARD3 -eq 0 ]; then
            restore_shard 2 "shard3" $host3
        fi

        if [ $CONFIG -eq 0 ]; then
            restore_config $config
        fi

        systemctl start mongos
        systemctl restart mongod*
    
    else
        echo "=> Start star restore"
        restore_star
    fi
fi
