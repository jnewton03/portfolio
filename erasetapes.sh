#!/bin/bash
set -e
ST_DRIVES=($(lsscsi -g | grep "tape"|awk '{print $6}'))
SG_DRIVES=($(lsscsi -g | grep "tape"|awk '{print $7}'))
SCSICHANGER=$(lsscsi -g | grep "mediumx"|awk '{print $7}')

#DRIVE=3
SLOTS=($(mtx -f /dev/sg15 status | grep -v CLN | grep -i full | tr ":" " " | awk '{print $3}'))
BARCODES=($(mtx -f /dev/sg15 status | grep -v CLN | grep -i full | awk -F= '{print $2}'))


s=0
while [ $s -lt ${#SLOTS[@]} ]; do
  for d in ${SG_DRIVES[@]}; do
    echo "moving tape ${BARCODES[$s]} to drive $d"
    #mtx -f $SCSICHANGER load ${SLOTS[$s]} $d
  let s=s+1
  done
  i=0
  for d in ${ST_DRIVES[@]}; do
    echo "rewinding tape ${BARCODES[$i]} in drive $d"
    #(mt -f ${ST_DRIVES[$i]} rewind && sg_format -T 0 ${SG_DRIVES[$i]}) &
  let i=i+1
  done
  for d in ${SG_DRIVES[@]}; do
    echo "moving tape ${BARCODES[$s]} back to slot"
    #mtx -f $SCSICHANGER unload $d
  let s=s+1
  done
  wait
done
