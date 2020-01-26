#!/bin/bash
printf "BME680 PythonToInfluxDB Service: Installer\n\n"

if [ $(id -u) -ne 0 ]; then
	printf "Script must be run as root. Try 'sudo ./install_service.sh'\n"
	exit 1
fi

printf "Stopping service \n"
systemctl disable BmeSensorInflux.service
systemctl stop BmeSensorInflux.service
systemctl daemon-reload
systemctl reset-failed

rm /lib/systemd/system/BmeSensorInflux.service

printf "Done!\n"
