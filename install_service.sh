#!/bin/bash
printf "BME680 PythonToInfluxDB Service: Installer\n\n"

if [ $(id -u) -ne 0 ]; then
	printf "Script must be run as root. Try 'sudo ./install_service.sh'\n"
	exit 1
fi

cp /home/pi/scripts/bme680_to_influxdb/BmeSensorInflux.service /lib/systemd/system/

printf "Starting service \n"
systemctl enable BmeSensorInflux.service
systemctl start BmeSensorInflux.service
systemctl daemon-reload

printf "Done!\n"
