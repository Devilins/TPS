#!/bin/bash

echo "Время выполнения джоба: $(date +%d-%m-%Y_%H-%M-%S)" >> /home/devilins/TPS/Dj_TPS/cron.log

/usr/bin/docker compose -f /home/devilins/TPS/Dj_TPS/docker-compose.yml exec tps bash -c '
	/usr/local/bin/python /app/manage.py run_sal_weekly $(date -d "-9 day" +%Y-%m-%d) $(date -d "-7 day" +%Y-%m-%d)
' >> /home/devilins/TPS/Dj_TPS/cron.log
