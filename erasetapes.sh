#!/bin/bash
set -x
TAPEDRIVE=/dev/nst0
SCSITAPE=/dev/sg6
SCSICHANGER=/dev/sg7
DRIVE=3
SLOTS=47

for tape in `seq 1 $SLOTS`;
do
    mtx -f $SCSICHANGER load $tape $DRIVE
    mt -f $TAPEDRIVE rewind
    sg_format -T 0 $SCSITAPE
    mtx -f $SCSICHANGER unload $tape $DRIVE
done

