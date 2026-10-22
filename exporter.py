import csv
import os
import time
from prometheus_client import start_http_server, Gauge

CSV_PATH = os.path.expanduser("~/sdn-project1/port_stats.csv")
labels = ["dpid", "port"]
rx_bps = Gauge("sdn_port_rx_bps", "Port receive rate in bits per second", labels)
tx_bps = Gauge("sdn_port_tx_bps", "Port transmit rate in bits per second", labels)
rx_bytes = Gauge("sdn_port_rx_bytes", "Port received bytes", labels)
tx_bytes = Gauge("sdn_port_tx_bytes", "Port transmitted bytes", labels)


def latest_rows():
    last = {}
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            if None in row.values():   # skip a half-written line
                continue
            last[(row["dpid"], row["port"])] = row
    return last


start_http_server(8000)
print("exporter listening on :8000")
while True:
    try:
        for (d, p), r in latest_rows().items():
            rx_bps.labels(d, p).set(float(r["rx_bps"]))
            tx_bps.labels(d, p).set(float(r["tx_bps"]))
            rx_bytes.labels(d, p).set(float(r["rx_bytes"]))
            tx_bytes.labels(d, p).set(float(r["tx_bytes"]))
    except (FileNotFoundError, ValueError):
        pass
    time.sleep(5)
