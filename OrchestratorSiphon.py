#!/bin/python3
import time #< Used to put the program to sleep to save CPU cycles
from datetime import datetime, timezone #< Keep track of timers and expiration of cached variables
import sys #< Used to exit the script
from getpass import getpass # Used to get user input without printing it to screen
import signal #< Used to catch terminal signals to switch to interactive mode
# Import our own libraries
from lib import Util, User, State


### Immediately start signal listeners - these are used to switch to interactive mode

"""
@brief Catches signals
"""
# Used for catching signals
signal_names = ['SIGINT','SIGQUIT','SIGTSTP']
signal_map = dict((getattr(signal, k), k) for k in signal_names)
def sigHandler(num, _):
    Util.log("Received signal: {0}".format(signal_map.get(num, '<other>')))
    if num == signal.SIGINT:
        sys.exit(1)
    Util.log("Will switch to interactive mode...")
    State.require_user_input = True
# Immediately enable listeners for each configured signal
for name in signal_names:
    signal.signal(getattr(signal, name), sigHandler)


### Orchestrator state


# This class initializes an Orchestrator object
class Orchestrator:
    def __init__(self, obj):
        # Orch details
        self.source_address = obj._source_address
        self.srcKeypath = obj._source_key
        # Get private key
        if obj._source_password == "":
            self.source_private_key = ""
        else:
            self.source_private_key = Util.getPrivateKey(obj._source_key, obj._source_password)
            # Immediately clear the text file containing the password
            if State.CLEAR_PASSWORD:
                Util.clearPassword(obj._source_password)
            # If the password was set via file or environment var but failed to decrypt, exit
            if self.source_private_key == "":
                Util.log("Fatal error: Unable to decrypt keystore file. Exiting...")
                exit(1)
        self.source_checksum_address = Util.getChecksumAddr(obj._source_address)
        # Set target adresses
        self.target_address_ETH = obj._target_address_eth
        self.target_checksum_address_ETH = Util.getChecksumAddr(obj._target_address_eth)
        self.receiver_address_LPT = obj._target_address_lpt
        self.receiver_checksum_address_LPT = Util.getChecksumAddr(obj._target_address_lpt)
        # LPT details
        self.previous_LPT_refresh = 0
        self.balance_LPT_pending = 0
        # ETH details
        self.previous_ETH_refresh = 0
        self.balance_ETH_pending = 0
        self.balance_ETH = 0
        # Round details
        self.previous_round_refresh = 0
        self.previous_reward_round = 0

# For each configured keystore, create a Orchestrator object
for obj in State.KEYSTORE_CONFIGS:
    Util.log("Adding Orchestrator '{0}'".format(obj._source_address))
    State.orchestrators.append(Orchestrator(obj))

# For each Orch with no password set, decrypt by user input
for i in range(len(State.orchestrators)):
    while State.orchestrators[i].source_private_key == "":
        State.orchestrators[i].source_private_key = Util.getPrivateKey(State.orchestrators[i].srcKeypath, getpass("Enter the password for {0}: ".format(State.orchestrators[i].source_address)))


### Main logic


# Now we have everything set up, endlessly loop
while True:
    current_time = datetime.now(timezone.utc).timestamp()
    if State.require_user_input:
        User.handleUserInput()
    else:
        # Main logic of refreshing cached variables and calling contract functions
        State.refreshState()
        # Sleep WAIT_TIME_IDLE seconds until next refresh 
        delay = State.WAIT_TIME_IDLE
        while delay > 0:
            # Exit early if we received a signal from the terminal
            if State.require_user_input:
                break
            Util.log("Sleeping for 10 seconds ({0} idle time left)".format(delay))
            if (delay > 10):
                delay = delay - 10
                time.sleep(10)
            else:
                time.sleep(delay)
                delay = 0