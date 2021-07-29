#! /usr/bin/env python3

import argparse
import json
import logging
import time

from btlewrap.bluepy import BluepyBackend
from miflora.miflora_poller import MiFloraPoller
from miflora.miflora_scanner import scan as miflora_scan
from prometheus_client import Counter, Gauge, start_http_server


error_count_metric = Counter('miflora_errors', 'The number of errors encountered while attempting to gather information from the probes', ['mac', 'plant'])
battery_level_metric = Gauge('miflora_battery_level_pct', 'The battery level of the probe', ['plant'])
conductivity_metric = Gauge('miflora_conductivity', 'Soil conductivity or whatever', ['plant'])
firmware_version_metric = Gauge('miflora_firmware_version', 'A mapping of probes to their respective firmware versions', ['plant', 'version'])
light_metric = Gauge('miflora_light', 'The ambient temperature (unit unknown)', ['plant'])
moisture_metric = Gauge('miflora_moisture', 'Soil moisture (unit unknown)', ['plant'])
temperature_metric = Gauge('miflora_temperature_c', 'The ambient temperature', ['plant'])


def load_plants(file):
    with open(file) as f:
        plants = json.load(f)
    assert isinstance(plants, dict)
    return plants


def scan_for_new_devices(plants):
    known_macs = set(plants.keys())
    nearby_macs = set(miflora_scan(BluepyBackend))
    new_macs = nearby_macs - known_macs

    if len(new_macs) == 0:
        print('no new devices detected')
        return
    for res in new_macs:
        print('new device: {}'.format(res))


def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description='Prometheus exporter for nearby miflora devices')
    parser.add_argument('plants', metavar='FILE', type=str,
                        help='JSON formatted file with MAC to name aliases')
    parser.add_argument('--scan', action=argparse.BooleanOptionalAction, default=False,
                        help='Perform a scan for devices not mapped in the plants file and exit')
    parser.add_argument('--port', type=int, default=9004,
                        help='The port number to bind the Prometheus exporter to')
    args = parser.parse_args()

    plants = load_plants(args.plants)
    if args.scan:
        scan_for_new_devices(plants)
        return

    start_http_server(args.port)
    logging.info('started prometheus exporter on port %d', args.port)

    pollers = [
        (mac, plant, MiFloraPoller(mac, BluepyBackend))
        for (mac, plant) in plants.items()
    ]
    # Update firmware versions only once.
    for (mac, plant, poller) in pollers:
        try:
            version = poller.firmware_version()
            firmware_version_metric.labels(plant=plant, version=version).set(1)
        except Exception as err:
            error_count_metric.labels(mac=mac, plant=plant).inc()
            logging.error('could not read probe %s (%s): %s', mac, plant, err)
        logging.info('initialized plant "%s" with probe MAC %s', plant, mac)

    while True:
        for (mac, plant, poller) in pollers:
            try:
                battery_level_metric.labels(plant=plant).set(poller.battery_level())
                conductivity_metric.labels(plant=plant).set(poller.parameter_value('conductivity'))
                light_metric.labels(plant=plant).set(poller.parameter_value('light'))
                moisture_metric.labels(plant=plant).set(poller.parameter_value('moisture'))
                temperature_metric.labels(plant=plant).set(poller.parameter_value('temperature'))
            except Exception as err:
                error_count_metric.labels(mac=mac, plant=plant).inc()
                logging.error('could not read probe %s (%s): %s', mac, plant, err)
        time.sleep(10 * 60)


main()
