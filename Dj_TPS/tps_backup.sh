#!/bin/bash

backupfolder=/home/devilins/TPS/Dj_TPS/pg_backups
sqlfile=$backupfolder/tps_db_prod-$(date +%d-%m-%Y_%H-%M-%S).sql
zipfile=$backupfolder/tps_db_prod-$(date +%d-%m-%Y_%H-%M-%S).zip
mkdir -p $backupfolder

if docker exec -t tps_postgres pg_dump -c -U tps_user_p tps_db > $sqlfile ; then
   echo 'Sql dump created'
else
   echo 'pg_dump return non-zero code'
   exit
fi

if gzip -c $sqlfile > $zipfile; then
   echo 'The backup file was successfully compressed'
else
   echo 'Error compressing backup'
   exit
fi
rm $sqlfile
echo $zipfile
