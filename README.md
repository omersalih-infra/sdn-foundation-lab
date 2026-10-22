# SDN Foundation Lab: Mininet + Ryu with Firewall and Live Monitoring

A small software-defined network built on Mininet and Open vSwitch, controlled by custom Ryu (OpenFlow 1.3) applications. It includes a learning switch, a controller-enforced firewall, and a live monitoring dashboard (Prometheus + Grafana).

This is Project 1 of an SDN series. Later projects build on this base (traffic engineering, intrusion detection, intent-based control).

## What it demonstrates

- Control-plane / data-plane separation: switches forward, the controller decides.
- A hand-written learning switch (reactive flow installation with idle timeouts).
- A firewall implemented as high-priority OpenFlow drop rules, enforced on every switch.
- Per-port throughput monitoring via OpenFlow port statistics, exported to Prometheus and shown in Grafana.

## Architecture

```
        Grafana :3000  <--  Prometheus :9090  <--  exporter.py :8000
                                                        |
                                                  port_stats.csv
                                                        ^
 Mininet (h1,h2,h3 / s1-s2-s3)  <--OpenFlow 1.3-->  Ryu :6653
   Open vSwitch                                    firewall_switch.py
                                                   stats_monitor.py
```

Topology (`mn --topo linear,3`): h1-s1, h2-s2, h3-s3, with s1-s2-s3 chained.

## Environment

| Component | Version |
|---|---|
| OS | Ubuntu Server 22.04 LTS (VMware Workstation VM) |
| Python | 3.10 |
| Mininet | 2.3.0 |
| Open vSwitch | 2.17.12 |
| Ryu | 4.34 (in a virtualenv) |
| eventlet / dnspython | 0.33.3 / 2.2.1 |
| Prometheus | Ubuntu package |
| Grafana | official apt repository |

## Files

| File | Purpose |
|---|---|
| `learning_switch.py` | Reactive L2 learning switch; installs flows with a 30 s idle timeout |
| `firewall_switch.py` | Learning switch plus drop rules at priority 100 (edit `RULES` to change policy) |
| `stats_monitor.py` | Polls port and flow stats every 5 s; writes `port_stats.csv`; logs firewall rule hits |
| `exporter.py` | Reads the CSV and exposes Prometheus metrics on port 8000 |

## Setup

```bash
sudo apt update && sudo apt -y install mininet openvswitch-switch python3-venv python3-pip iperf3 tcpdump net-tools git curl

python3 -m venv ~/ryu-env
source ~/ryu-env/bin/activate
pip install "setuptools<68" wheel
pip install ryu
pip install eventlet==0.33.3 dnspython==2.2.1 prometheus_client
```

Ryu 4.34 does not start on Python 3.10 out of the box. Two fixes were needed:

1. Newer `eventlet` and `dnspython` versions (above) replace the pinned older ones, which break on Python 3.10.
2. `eventlet` removed `ALREADY_HANDLED`, which `ryu/app/wsgi.py` imports. It is replaced with a stub (this only affects Ryu's websocket support, which this project does not use):

```bash
sed -i 's/from eventlet.wsgi import ALREADY_HANDLED/ALREADY_HANDLED = []/' \
  ~/ryu-env/lib/python3.10/site-packages/ryu/app/wsgi.py
```

Reinstalling Ryu overwrites this patch; apply it again if you do.

## Run

```bash
# Terminal 1: controller (firewall + monitor)
source ~/ryu-env/bin/activate
ryu-manager ~/sdn-project1/firewall_switch.py ~/sdn-project1/stats_monitor.py

# Terminal 2: network
sudo mn --topo linear,3 --controller remote,ip=127.0.0.1,port=6653 --switch ovsk,protocols=OpenFlow13

# Terminal 3: metrics exporter
source ~/ryu-env/bin/activate
python3 ~/sdn-project1/exporter.py
```

Prometheus job (appended to `/etc/prometheus/prometheus.yml`):

```yaml
  - job_name: 'sdn'
    scrape_interval: 5s
    static_configs:
      - targets: ['localhost:8000']
```

Grafana panel query: `sdn_port_tx_bps` (unit: bits/sec SI). Note that the Ubuntu-packaged Prometheus serves its status pages under `/classic/` (for example `/classic/targets`).

## Firewall policy

| Rule | Effect |
|---|---|
| h1 <-> h3, all IP | dropped |
| h2 -> h3, TCP port 80 | dropped |
| everything else | allowed (learning switch) |

## Results

| Test | Result |
|---|---|
| Single switch, `pingall` | 0% dropped; 6 learned flows plus table-miss entry |
| Learned flows after 30 s idle | expired; relearned on next traffic |
| Linear 3-switch, `pingall` | 33% dropped (only h1 <-> h3 blocked), as designed |
| h1 -> h3 ping | 100% loss; 10 packets counted on the s1 drop rule |
| h2 -> h3 on TCP 80 / 8080 | 80 timed out, 8080 served |
| Where drops happen | at the first switch the blocked packet enters; s2 counters stayed at 0 |
| Throughput, 60 s `iperf3` h2 -> h3 | sender 23.0 Gbit/s average (161 GB transferred, 224 retransmits); Grafana showed a 23.3 Gb/s peak on s3 port 1, with load only on s2/s3 and none on s1 |

The monitor and `iperf3` agree for the long run. An earlier short run using Mininet's built-in `iperf` command (about 29 Gbit/s reported) did not match the monitor's average (about 14.5 Gbit/s); the cause was not established, and short tests can fall between the 5 s polling windows. These are software-switch numbers on a VM, not hardware performance.

## Lessons learned

- Verify Python-version compatibility of older frameworks (Ryu) before building on them.
- Enforcing a policy at every switch drops traffic at the network edge instead of carrying it across the core.
- Run web servers and eventlet-based apps in separate processes; the exporter reads the monitor's CSV instead of living inside Ryu.
- An idle network produces a flat dashboard; load tests need to be long enough to span several scrape intervals.

## Next steps

- Multi-path topology with load balancing and rerouting on congestion.
- Anomaly / DDoS detection using the flow statistics collected here.
- Intent-based control: natural-language policies translated to validated OpenFlow rules.
