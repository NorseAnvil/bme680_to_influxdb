#!/usr/bin/env python
import time  # for time and delay
import sys  # for arguments
import datetime  # for time and delay
from influxdb import InfluxDBClient  # for collecting data
from influxdb.exceptions import InfluxDBClientError # for handling client errors writing to influx
from influxdb.exceptions import InfluxDBServerError # for handling server errors writing to influx
import socket  # for hostname
import bme680  # for sensor data
import configparser  # for parsing config.ini file
import urllib3  # For option to disable warnings if using self signed certs and htttp/https exceptions
import systemd.daemon

def get_raspid():
    # Extract serial from cpuinfo file
    cpuserial = "0000000000000000"
    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if line[0:6] == 'Serial':
                cpuserial = line[10:26]
    return cpuserial


# Allow user to set session and runno via args otherwise auto-generate
if len(sys.argv) is 2:
    configpath = sys.argv[1]
else:
    print("ParameterError: You must define the path to the config.ini!")
    sys.exit()

# Parsing the config parameters from config.ini
config = configparser.ConfigParser()
try:
    config.read(configpath)
    influxserver = config['influxserver']
    host = influxserver.get('host')
    port = influxserver.get('port')
    user = influxserver.get('user')
    password = influxserver.get('password')
    dbname = influxserver.get('dbname')
    enable_https = influxserver.getboolean('enable_https')
    insecure_skip_verify = not influxserver.getboolean('insecure_skip_verify')
    disable_bad_https_warning = influxserver.getboolean(
        'disable_bad_https_warning')
    sensor = config['sensor']
    enable_gas = sensor.getboolean('enable_gas')
    session = sensor.get('session')
    location = sensor.get('location')
    temp_offset = float(sensor['temp_offset'])
    interval = int(sensor['interval'])
    burn_in_time = float(sensor['burn_in_time'])
except TypeError:
    print("TypeError parsing config.ini file. Check boolean datatypes!")
    sys.exit()
except KeyError:
    print("KeyError parsing config.ini file. Check file and its structure!")
    sys.exit()
except ValueError:
    print("ValueError parsing config.ini file. Check number datatypes!")
    sys.exit()

# Tell systemd that our service is ready
systemd.daemon.notify('READY=1')

# disable warnings with tls and selfsigned certs
if disable_bad_https_warning:
    urllib3.disable_warnings()

sensor = bme680.BME680()
raspid = get_raspid()
now = datetime.datetime.now()
runNo = now.strftime("%Y%m%d%H%M")
hostname = socket.gethostname()
DBTimeout = 5  # 5 sec timeout for db writeing

print("Session: ", session)
print("runNo: ", runNo)
print("raspid: ", raspid)
print("hostname: ", hostname)
print("location: ", location)

# Create the InfluxDB object
DBclient = InfluxDBClient(host,
                          port, user, password, dbname,
                          enable_https, insecure_skip_verify, DBTimeout)


# BME680 configuration
# Set sensor configs
sensor.set_humidity_oversample(bme680.OS_2X)
sensor.set_pressure_oversample(bme680.OS_4X)
sensor.set_temperature_oversample(bme680.OS_8X)
sensor.set_filter(bme680.FILTER_SIZE_3)
sensor.set_temp_offset(temp_offset)

if enable_gas:
    sensor.set_gas_status(bme680.ENABLE_GAS_MEAS)
    sensor.set_gas_heater_temperature(320)
    sensor.set_gas_heater_duration(150)
    sensor.select_gas_heater_profile(0)
else:
    sensor.set_gas_status(bme680.DISABLE_GAS_MEAS)

# start_time and curr_time ensure that the
# burn_in_time (in seconds) is kept track of.
start_time = time.time()
curr_time = time.time()
burn_in_data = []

# initializing variables for json
Influx_json = []
hum = 0
temp = 0
press = 0
iso = 0
gas = 0
air_quality_score = 0
gas_baseline = 0
null = None

# Set the humidity baseline to 40%, an optimal indoor humidity.
hum_baseline = 40.0
# This sets the balance between humidity and gas reading in the
# # calculation of air_quality_score (25:75, humidity:gas)
hum_weighting = 0.25


# method for create Json object to write to influx
def CreateJsonBody(
        session, runNo, raspid, hostname,
        location, iso, temp, press, hum,
        gas, air_quality_score, gas_baseline,
        hum_baseline):
    new_json = [
        {
            "measurement": session,
            "tags": {
                "run": runNo,
                "raspid": raspid,
                "hostname": hostname,
                "location": location
            },
            "time": iso,
            "fields": {
                "temp": temp,
                "press": press,
                "humi": hum,
                "gas": gas,
                "iaq": air_quality_score,
                "gasbaseline": gas_baseline,
                "humbaseline": hum_baseline
            }
        }
    ]
    return(new_json)

# Method for writing to influx


def WriteToInflux(jsonToInflux):
    try:
        # Write JSON to InfluxDB
        res = DBclient.write_points(jsonToInflux)
        print(res, "Influx written")
    except InfluxDBClientError as Influx_error:
        print(str(Influx_error))
        print("Error in the request from InfluxDBClient!")
        pass
    except InfluxDBServerError as Influx_error:
        print(str(Influx_error))
        print("Influx DB Server error thrown!")
        pass
    except ConnectionError as ConnError:
        print("Error Connecting")
        print(str(ConnError))
        pass
    except UrlExceptions.ConnectTimeoutError as Url1Error:
        print("HTTP/HTTPS Connection Error:")
        print(str(Url1Error))
    except UrlExceptions.ConnectionError as Url2Error:
        print("HTTP/HTTPS Connection Error:")
        print(str(Url2Error))
    except Exception as UnhandeledError:
        print("Exception: " + str(UnhandeledError))
        pass


# Run until keyboard out
try:
    # Collect gas resistance burn-in values, then use the average
    # of the last 300 values (5min) to set the upper limit for calculating
    # gas_baseline.
    if enable_gas:
        print("Collecting gas resistance burn-in data\n")
        while curr_time - start_time < burn_in_time:
            curr_time = time.time()
            if sensor.get_sensor_data() and sensor.data.heat_stable:
                gas = sensor.data.gas_resistance
                burn_in_data.append(gas)
                print("Gas: {0} Ohms".format(gas))
                # Sent data to influx while we wait for gas to
                # establish baseline
                hum = sensor.data.humidity
                temp = sensor.data.temperature
                press = sensor.data.pressure
                iso = time.ctime()
                # Write data to influx
                Influx_json = CreateJsonBody(
                    session,
                    runNo,
                    raspid,
                    hostname,
                    location,
                    iso,
                    temp,
                    press,
                    hum,
                    null,
                    null,
                    null,
                    null,)
                WriteToInflux(Influx_json)
            time.sleep(1)

        # Calculate Gas Baseline
        gas_baseline = int(sum(burn_in_data[-300:]) / 300.0)

        print(
            "Gas baseline: {0} Ohms, humidity baseline: {1:.2f} %RH\n".format(
                gas_baseline,
                hum_baseline))

    # Sensor read loop
    while True:
        if sensor.get_sensor_data():
            hum = sensor.data.humidity
            temp = sensor.data.temperature
            press = sensor.data.pressure
            iso = time.ctime()

            if enable_gas:
                hum_offset = hum - hum_baseline
                gas = int(sensor.data.gas_resistance)
                gas_offset = gas_baseline - gas

                # Calculate hum_score as the distance from the hum_baseline.
                if hum_offset > 0:
                    hum_score = (100 - hum_baseline - hum_offset) / \
                        (100 - hum_baseline) * (hum_weighting * 100)
                else:
                    hum_score = (hum_baseline + hum_offset) / \
                        hum_baseline * (hum_weighting * 100)

                # Calculate gas_score as the distance from the gas_baseline.
                if gas_offset > 0:
                    gas_score = (gas / gas_baseline) * \
                        (100 - (hum_weighting * 100))
                else:
                    gas_score = 100 - (hum_weighting * 100)

                # Calculate air_quality_score.
                air_quality_score = hum_score + gas_score
                # Round to full
                air_quality_score = round(air_quality_score, 0)
                # Create Json body
                Influx_json = CreateJsonBody(
                    session, runNo, raspid, hostname,
                    location, iso, temp, press, hum,
                    gas, air_quality_score,
                    gas_baseline, hum_baseline)

            else:
                Influx_json = CreateJsonBody(
                    session,
                    runNo,
                    raspid,
                    hostname,
                    location,
                    iso,
                    temp,
                    press,
                    hum,
                    null,
                    null,
                    null,
                    null)

            # Write data to influx
            print("influxJson: ", Influx_json)
            WriteToInflux(Influx_json)
            # Wait for next sample
            time.sleep(interval)
        else:
            print("Error: .get_sensor_data() or heat_stable failed.")
            break

        # Wait for next sample
        time.sleep(interval)

except KeyboardInterrupt:
    pass
