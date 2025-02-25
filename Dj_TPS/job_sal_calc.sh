#!/bin/bash

echo "Время выполнения джоба: $(date +%d-%m-%Y_%H-%M-%S)" >> /home/devilins/TPS/Dj_TPS/cron.log

/usr/bin/docker compose -f /home/devilins/TPS/Dj_TPS/docker-compose.yml exec tps bash -c '
    /usr/local/bin/python /app/manage.py run_sal_calc $(date +\%Y-\%m-\%d) $(date +\%Y-\%m-\%d)
' >> /home/devilins/TPS/Dj_TPS/cron.log
