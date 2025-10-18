import argparse
import asyncio
import os
import threading
import time

import LXMF
import RNS


class EchoBot:

    def __init__(self, identity: RNS.Identity, display_name: str, announce_interval_seconds: int | None = None, max_outbound_stamp_cost: int | None = None):

        self.identity = identity
        self.display_name = display_name
        self.path_lookup_timeout_seconds = 15
        self.announce_interval_seconds = announce_interval_seconds
        self.max_outbound_stamp_cost = max_outbound_stamp_cost
        self.last_announced_at = None

        # Init RNS
        self.reticulum = RNS.Reticulum()

        # Init LXMF router
        self.message_router = LXMF.LXMRouter(identity=self.identity, storagepath="./lxmf_storage")

        # Register LXMF identity
        self.local_lxmf_destination = self.message_router.register_delivery_identity(
            identity=self.identity,
            display_name=self.display_name,
        )

        # Set callback for inbound messages
        self.message_router.register_delivery_callback(self.on_lxmf_message_received)

        # Announce now
        self.announce()

        # Start auto announce thread
        thread = threading.Thread(target=self.announce_loop)
        thread.daemon = True
        thread.start()

    def announce_loop(self):
        while True:
            should_announce = False
            if self.announce_interval_seconds and self.announce_interval_seconds > 0:
                if self.last_announced_at is None or time.time() > self.last_announced_at + self.announce_interval_seconds:
                    should_announce = True
            if should_announce:
                self.announce()
            time.sleep(1)

    def announce(self):
        self.last_announced_at = int(time.time())
        self.message_router.announce(destination_hash=self.local_lxmf_destination.hash)

    def get_online_nodes_full(self, max_age_seconds=60):
        nodes = {}
        for iface in RNS.Transport.interfaces:
            peers = getattr(iface, "peers", []) or []
            for p in peers:
                nodes[p.hex()] = {"interface": iface.name, "type": "peer"}

        now = time.time()
        for dst_hash, path_info in RNS.Transport.path_table.items():
            last_seen = path_info[0]
            if now - last_seen <= max_age_seconds:
                nodes[dst_hash.hex()] = {"via": str(path_info[1]), "hops": path_info[2], "type": "path"}

        return list(nodes.values())

    def format_mesh_info(self, stats: dict) -> str:
        lines = ["📡 **Mesh Network Status**", ""]

        for iface in stats.get("interfaces", []):
            lines.append(f"🔹 Interface: {iface['short_name']} ({iface['type']})")
            lines.append(f"   ├ Status: {'🟢 Online' if iface['status'] else '🔴 Offline'}")
            lines.append(f"   ├ Mode: {iface['mode']}")
            lines.append(f"   ├ RX bytes: {iface['rxb']}  |  TX bytes: {iface['txb']}")
            lines.append(f"   ├ RX speed: {iface['rxs']:.2f} B/s  |  TX speed: {iface['txs']:.2f} B/s")
            if iface.get("bitrate"):
                lines.append(f"   ├ Bitrate: {iface['bitrate']:.2f} bps")
            if iface.get("noise_floor") is not None:
                lines.append(f"   ├ Noise floor: {iface['noise_floor']} dBm")
            if iface.get("battery_percent") is not None:
                lines.append(f"   ├ Battery: {iface['battery_percent']}%")
            if iface.get("airtime_short") is not None:
                lines.append(f"   ├ Airtime (short): {iface['airtime_short']:.2f}%")
            if iface.get("airtime_long") is not None:
                lines.append(f"   ├ Airtime (long): {iface['airtime_long']:.2f}%")
            lines.append(f"   └ Peers: {iface['peers']}")
            lines.append("")

        lines.append("🌐 **Transport Statistics:**")
        lines.append(f"   ├ Known nodes: {stats.get('known_nodes', 0)}")
        lines.append(f"   ├ Total RX bytes: {stats.get('total_rx_bytes', 0)}")
        lines.append(f"   ├ Total TX bytes: {stats.get('total_tx_bytes', 0)}")
        lines.append(f"   ├ RX speed: {stats.get('rx_speed', 0.0):.2f} B/s")
        lines.append(f"   ├ TX speed: {stats.get('tx_speed', 0.0):.2f} B/s")
        lines.append(f"   └ Uptime: {stats.get('transport_uptime', 0.0):.1f} s")

        return "\n".join(lines)

    def on_lxmf_message_received(self, lxmf_message: LXMF.LXMessage):
        destination_hash = lxmf_message.source_hash
        print(f"📨 Received message from {destination_hash.hex()}: {lxmf_message.content_as_string()}")

        if not RNS.Transport.has_path(destination_hash):
            print(f"Requesting path to {destination_hash.hex()}")
            RNS.Transport.request_path(destination_hash)
            timeout_after_seconds = time.time() + self.path_lookup_timeout_seconds
            while not RNS.Transport.has_path(destination_hash) and time.time() < timeout_after_seconds:
                time.sleep(0.1)

        destination_identity = RNS.Identity.recall(destination_hash)
        if destination_identity is None:
            print(f"Path not found, unable to reply to {destination_hash.hex()}")
            return

        lxmf_destination = RNS.Destination(destination_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")

        if self.max_outbound_stamp_cost is not None and self.message_router.get_outbound_ticket(destination_hash) is None:
            outbound_stamp_cost = self.message_router.get_outbound_stamp_cost(destination_hash)
            if outbound_stamp_cost and outbound_stamp_cost > self.max_outbound_stamp_cost:
                print(f"Not replying due to high stamp cost ({outbound_stamp_cost})")
                return

        desired_delivery_method = LXMF.LXMessage.DIRECT
        if not self.message_router.delivery_link_available(destination_hash) and RNS.Identity.current_ratchet_id(destination_hash) is not None:
            desired_delivery_method = LXMF.LXMessage.OPPORTUNISTIC

        reply_text = (
            f"Echo reply from echo bot\n"
            f"\n"
            f"Received RSSI: {lxmf_message.rssi}, SNR: {lxmf_message.snr}\n\n"
            f"Content: {lxmf_message.content_as_string()}\n\n"
        )

        lxmf_message_reply = LXMF.LXMessage(
            destination=lxmf_destination,
            source=self.local_lxmf_destination,
            title=lxmf_message.title,
            content=reply_text,
            fields=lxmf_message.fields,
            desired_method=desired_delivery_method,
        )

        lxmf_message_reply.register_delivery_callback(self.on_lxmf_sending_success)
        lxmf_message_reply.register_failed_callback(self.on_lxmf_sending_failed)

        print(f"📤 Sending reply to {destination_hash.hex()}")
        self.message_router.handle_outbound(lxmf_message_reply)

    def on_lxmf_sending_success(self, lxmf_message: LXMF.LXMessage):
        print(f"✅ Successfully sent reply to {lxmf_message.destination_hash.hex()}")

    def on_lxmf_sending_failed(self, lxmf_message: LXMF.LXMessage):
        print(f"❌ Failed to send reply to {lxmf_message.destination_hash.hex()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LXMF Echo Bot with Mesh Info")
    parser.add_argument("--identity-file", type=str, required=True)
    parser.add_argument("--display-name", type=str, required=True)
    parser.add_argument("--announce-interval-seconds", type=int)
    parser.add_argument("--max-outbound-stamp-cost", type=int)
    args = parser.parse_args()

    if not os.path.exists(args.identity_file):
        identity = RNS.Identity(create_keys=True)
        with open(args.identity_file, "wb") as file:
            file.write(identity.get_private_key())
        print(f"Generated new identity: {identity.hash.hex()}")

    identity = RNS.Identity(create_keys=False)
    identity.load(args.identity_file)
    print(f"Loaded identity: {identity.hash.hex()}")

    echobot = EchoBot(
        identity=identity,
        display_name=args.display_name,
        announce_interval_seconds=args.announce_interval_seconds,
        max_outbound_stamp_cost=args.max_outbound_stamp_cost,
    )

    loop = asyncio.new_event_loop()
    loop.run_forever()
