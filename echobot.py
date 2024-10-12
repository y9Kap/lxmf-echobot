import argparse
import asyncio
import os
import threading
import time

import LXMF
import RNS


class EchoBot:

    def __init__(self, identity: RNS.Identity, display_name: str, announce_interval_seconds: int | None = None):

        # remember variables
        self.identity = identity
        self.display_name = display_name
        self.path_lookup_timeout_seconds = 15
        self.announce_interval_seconds = announce_interval_seconds
        self.last_announced_at = None

        # init rns
        self.reticulum = RNS.Reticulum()

        # init lxmf router
        self.message_router = LXMF.LXMRouter(identity=self.identity, storagepath="./lxmf_storage")

        # register lxmf identity
        self.local_lxmf_destination = self.message_router.register_delivery_identity(
            identity=self.identity,
            display_name=self.display_name,
        )

        # set a callback for when an lxmf message is received
        self.message_router.register_delivery_callback(self.on_lxmf_message_received)

        # announce on start up
        self.announce()

        # start background thread to auto announce
        thread = threading.Thread(target=self.announce_loop)
        thread.daemon = True
        thread.start()

    # automatically announces our lxmf address
    def announce_loop(self):
        while True:

            should_announce = False

            # check if auto announce is enabled
            if self.announce_interval_seconds is not None and self.announce_interval_seconds > 0:

                # check if we have announced recently
                if self.last_announced_at is not None:

                    # determine when next announce should be sent
                    next_announce_at = self.last_announced_at + self.announce_interval_seconds

                    # we should announce if current time has passed next announce at timestamp
                    if time.time() > next_announce_at:
                        should_announce = True

                else:

                    # last announced at is null, so we have never announced, lets do it now
                    should_announce = True

            # announce
            if should_announce:
                self.announce()

            # wait 1 second before next loop
            time.sleep(1)

    # sends an announce
    def announce(self):

        # update last announced at timestamp
        self.last_announced_at = int(time.time())

        # send announce for lxmf address
        self.message_router.announce(destination_hash=self.local_lxmf_destination.hash)

    # handle a received lxmf message
    def on_lxmf_message_received(self, lxmf_message: LXMF.LXMessage):

        # check who sent us this message
        destination_hash = lxmf_message.source_hash
        print(f"Received message from {destination_hash.hex()}: {lxmf_message.content}")

        # check if we have a path to the sender
        if not RNS.Transport.has_path(destination_hash):

            # we don't have a path, so we need to request it
            print(f"Requesting path to {destination_hash.hex()}")
            RNS.Transport.request_path(destination_hash)

            # wait until we have a path, or give up after the configured timeout
            timeout_after_seconds = time.time() + self.path_lookup_timeout_seconds
            while not RNS.Transport.has_path(destination_hash) and time.time() < timeout_after_seconds:
                time.sleep(0.1)

        # find destination identity from hash
        destination_identity = RNS.Identity.recall(destination_hash)
        if destination_identity is None:

            # we have to bail out of replying, since we don't have the identity/path yet
            print(f"Path not found, unable to reply to {destination_hash.hex()}")
            return

        # create destination for recipients lxmf delivery address
        lxmf_destination = RNS.Destination(destination_identity, RNS.Destination.OUT, RNS.Destination.SINGLE, "lxmf", "delivery")

        # todo check the stamp cost to message the user, if no ticket available, and cost is very high, don't reply to prevent cpu death

        # create a new lxmf message to the user that messaged us with the same content they sent us
        lxmf_message_reply = LXMF.LXMessage(
            destination=lxmf_destination, # send our message to the user that messaged us
            source=self.local_lxmf_destination, # we are the source of this message
            title=lxmf_message.title, # send the received title back
            content=lxmf_message.content, # send the received content back
            fields=lxmf_message.fields, # send the received fields back
            desired_method=lxmf_message.method, # use the same method to reply that was used to message us
        )

        # listen for success or failure for sending message
        lxmf_message_reply.register_delivery_callback(self.on_lxmf_sending_success)
        lxmf_message_reply.register_failed_callback(self.on_lxmf_sending_failed)

        # send the lxmf message
        print(f"Sending reply to {destination_hash.hex()}")
        self.message_router.handle_outbound(lxmf_message_reply)

    # handle delivery failed for an outbound lxmf message
    def on_lxmf_sending_success(self, lxmf_message: LXMF.LXMessage):
        print(f"Successfully sent reply to {lxmf_message.destination_hash.hex()}")

    # handle delivery failed for an outbound lxmf message
    def on_lxmf_sending_failed(self, lxmf_message: LXMF.LXMessage):
        print(f"Failed to send reply to {lxmf_message.destination_hash.hex()}")

if __name__ == "__main__":

    # parse command line args
    parser = argparse.ArgumentParser(description="Liam's LXMF Echo Bot")
    parser.add_argument("--identity-file", type=str, help="Path to a Reticulum Identity file to use as the LXMF address.", required=True)
    parser.add_argument("--display-name", type=str, help="The display name to send in announces.", required=True)
    parser.add_argument("--announce-interval-seconds", type=int, help="How often the EchoBot should announce.")
    args = parser.parse_args()

    # if identity file does not exist, generate a new identity and save it
    if not os.path.exists(args.identity_file):
        identity = RNS.Identity(create_keys=True)
        with open(args.identity_file, "wb") as file:
            file.write(identity.get_private_key())
        print("Reticulum Identity <{}> has been randomly generated and saved to {}.".format(identity.hash.hex(), args.identity_file))

    # load identity file
    identity = RNS.Identity(create_keys=False)
    identity.load(args.identity_file)
    print("Reticulum Identity <{}> has been loaded from file {}.".format(identity.hash.hex(), args.identity_file))

    # start echo bot
    echobot = EchoBot(
        identity=identity,
        display_name=args.display_name,
        announce_interval_seconds=args.announce_interval_seconds,
    )

    # loop forever to prevent script exiting immediately
    loop = asyncio.new_event_loop()
    loop.run_forever()
