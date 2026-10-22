import csv
import os
import time
from operator import attrgetter

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

INTERVAL = 5  # seconds between polls
CSV_PATH = os.path.expanduser("~/sdn-project1/port_stats.csv")


class StatsMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.prev = {}   # (dpid, port) -> (rx_bytes, tx_bytes, timestamp)
        new_file = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
        self.csv_file = open(CSV_PATH, "a", newline="")
        self.writer = csv.writer(self.csv_file)
        if new_file:
            self.writer.writerow(["time", "dpid", "port", "rx_bytes", "tx_bytes",
                                  "rx_bps", "tx_bps", "rx_dropped", "tx_dropped"])
        hub.spawn(self._poll_loop)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.logger.info("monitor: tracking switch %s", dp.id)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)

    def _poll_loop(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser = dp.ofproto_parser
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
                dp.send_msg(parser.OFPFlowStatsRequest(dp))
            hub.sleep(INTERVAL)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_handler(self, ev):
        dpid = ev.msg.datapath.id
        now = time.time()
        for st in sorted(ev.msg.body, key=attrgetter("port_no")):
            if st.port_no > ofproto_v1_3.OFPP_MAX:   # skip the LOCAL port
                continue
            key = (dpid, st.port_no)
            rx_bps = tx_bps = 0.0
            if key in self.prev:
                prx, ptx, pt = self.prev[key]
                dt = now - pt
                if dt > 0:
                    rx_bps = (st.rx_bytes - prx) * 8 / dt
                    tx_bps = (st.tx_bytes - ptx) * 8 / dt
            self.prev[key] = (st.rx_bytes, st.tx_bytes, now)
            self.writer.writerow([int(now), dpid, st.port_no, st.rx_bytes, st.tx_bytes,
                                  int(rx_bps), int(tx_bps), st.rx_dropped, st.tx_dropped])
            self.csv_file.flush()
            if rx_bps > 0 or tx_bps > 0:
                self.logger.info("PORT s%s p%s rx=%.1f Kbps tx=%.1f Kbps",
                                 dpid, st.port_no, rx_bps / 1e3, tx_bps / 1e3)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_handler(self, ev):
        dpid = ev.msg.datapath.id
        for st in ev.msg.body:
            if st.priority == 100 and st.packet_count > 0:
                self.logger.info("FIREWALL s%s hits=%d match=%s",
                                 dpid, st.packet_count, st.match)
