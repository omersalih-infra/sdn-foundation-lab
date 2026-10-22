from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types

# Firewall policy: edit this list to change the rules
RULES = [
    # h1 <-> h3: block all IP traffic in both directions
    {"src": "10.0.0.1", "dst": "10.0.0.3", "both": True},
    # h2 -> h3: block only web traffic (TCP port 80)
    {"src": "10.0.0.2", "dst": "10.0.0.3", "proto": 6, "dport": 80, "both": False},
]


class FirewallSwitch(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.add_flow(dp, 0, parser.OFPMatch(), actions)
        self.install_firewall(dp)
        self.logger.info("switch %s connected, firewall installed", dp.id)

    def install_firewall(self, dp):
        parser = dp.ofproto_parser
        for r in RULES:
            fields = {"eth_type": 0x0800, "ipv4_src": r["src"], "ipv4_dst": r["dst"]}
            if "proto" in r:
                fields["ip_proto"] = r["proto"]
                if r["proto"] == 6:
                    fields["tcp_dst"] = r["dport"]
            self.add_flow(dp, 100, parser.OFPMatch(**fields), [])   # no actions = drop
            if r.get("both"):
                rev = dict(fields, ipv4_src=r["dst"], ipv4_dst=r["src"])
                self.add_flow(dp, 100, parser.OFPMatch(**rev), [])
            self.logger.info("DROP rule: %s", r)

    def add_flow(self, dp, priority, match, actions, idle_timeout=0):
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                instructions=inst, idle_timeout=idle_timeout)
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        dst, src = eth.dst, eth.src
        self.mac_to_port.setdefault(dp.id, {})[src] = in_port
        out_port = self.mac_to_port[dp.id].get(dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(dp, 1, match, actions, idle_timeout=30)
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)
