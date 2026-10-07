#!/bin/python3
import time #< Used to put the program to sleep to save CPU cycles
from datetime import datetime, timezone #< Keep track of timers and expiration of cached variables
import sys #< Used to exit the script
from getpass import getpass # Used to get user input without printing it to screen
import signal #< Used to catch terminal signals to switch to interactive mode
import argparse #< Used to launch the program locked into interactive mode
# Import our own libraries
from lib import Util, Contract, User, State


### Immediately start signal listeners - these are used to switch to interactive mode


# The signals we're listening for
signal_names = ['SIGINT','SIGQUIT','SIGTSTP']
# Lookup table so we can translate back to a name for printing
signal_map = dict((getattr(signal, k), k) for k in signal_names)

"""
@brief Catches signals
@param num: Number corresponding to the signal name
@param _: ignored, but required when attaching the signal handler
"""
def sigHandler(num, _):
    Util.log("Received signal: {0}".format(signal_map.get(num, '<other>')), 2)
    if num == signal.SIGINT:
        sys.exit(1)
    Util.log("Will switch to interactive mode...", 2)
    State.require_user_input = True
# Immediately enable listeners for each configured signal
for name in signal_names:
    signal.signal(getattr(signal, name), sigHandler)


### Parse launch arguments


parser = argparse.ArgumentParser(description="Orchestrator Siphon")
parser.add_argument(
    '-i', '-it', '--interactive', action='store_true', help="Launch the program locked in interactive mode."
)
args, unknown = parser.parse_known_args()
if unknown:
    Util.log(f"Warning: Skipping unknown arguments: {', '.join(unknown)}", 1)
State.LOCK_INTERACTIVE = getattr(args, 'interactive', False) or getattr(args, 'it', False) or getattr(args, 'i', False)
State.require_user_input = State.LOCK_INTERACTIVE


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
                Util.log("Fatal error: Unable to decrypt keystore file. Exiting...", 1)
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
    Util.log("Adding Orchestrator '{0}'".format(obj._source_address), 2)
    State.orchestrators.append(Orchestrator(obj))

# For each Orch with no password set, decrypt by user input
for i in range(len(State.orchestrators)):
    while State.orchestrators[i].source_private_key == "":
        State.orchestrators[i].source_private_key = Util.getPrivateKey(State.orchestrators[i].srcKeypath, getpass("Enter the password for {0}: ".format(State.orchestrators[i].source_address)))


### Main logic


"""
@brief Checks all Orchestrators if any cached data needs refreshing or contracts need calling
"""
def refreshState():
    if State.require_user_input:
        return
    # Check for round updates
    if current_time < State.previous_round_refresh + State.WAIT_TIME_ROUND_REFRESH:
        if State.current_round_is_locked:
            Util.log("(cached) Round status: round {0} (locked). Refreshing in {1:.0f} seconds...".format(State.current_round_num, State.WAIT_TIME_ROUND_REFRESH - (current_time - State.previous_round_refresh)), 3)
        else:
            Util.log("(cached) Round status: round {0} (unlocked). Refreshing in {1:.0f} seconds...".format(State.current_round_num, State.WAIT_TIME_ROUND_REFRESH - (current_time - State.previous_round_refresh)), 3)
    else:
        Contract.refreshRound()
        Contract.refreshLock()

    # Now check each Orch keystore for expired cached values and do stuff
    for i in range(len(State.orchestrators)):
        Util.log("Refreshing Orchestrator '{0}'".format(State.orchestrators[i].source_address), 2)

        # First check if we need to call reward. This happens before moving any stake or fees, since those txs claim the
        # Orch's earnings, after which rewards from the same round can only be moved in the next round
        if State.orchestrators[i].previous_reward_round >= State.current_round_num:
            Util.log("'{0}' has already called reward this round".format(State.orchestrators[i].source_address), 3)
        else:
            # Refresh Orch reward round
            if current_time < State.orchestrators[i].previous_round_refresh + State.WAIT_TIME_ROUND_REFRESH:
                Util.log("(cached) {0}'s last reward round is {1}. Refreshing in {2:.0f} seconds...".format(State.orchestrators[i].source_address, State.orchestrators[i].previous_reward_round, State.WAIT_TIME_ROUND_REFRESH - (current_time - State.orchestrators[i].previous_round_refresh)), 3)
            else:
                Contract.refreshRewardRound(i)

            # Call reward
            if State.orchestrators[i].previous_reward_round < State.current_round_num:
                Contract.doCallReward(i)
                Contract.refreshRewardRound(i)
                Contract.refreshStake(i)
            else:
                Util.log("{0} has already called reward in round {1}".format(State.orchestrators[i].source_address, State.current_round_num), 3)

        # Then check pending LPT
        if current_time < State.orchestrators[i].previous_LPT_refresh + State.WAIT_TIME_LPT_REFRESH:
            Util.log("(cached) {0}'s pending stake is {1:.2f} LPT. Refreshing in {2:.0f} seconds...".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_LPT_pending, State.WAIT_TIME_LPT_REFRESH - (current_time - State.orchestrators[i].previous_LPT_refresh)), 3)
        else:
            Contract.refreshStake(i)

        # Transfer pending LPT if threshold is reached
        if State.orchestrators[i].balance_LPT_pending < State.LPT_THRESHOLD:
            Util.log("{0} has {1:.2f} LPT in pending stake < threshold of {2:.2f} LPT".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_LPT_pending, State.LPT_THRESHOLD), 3)
        elif State.LPT_MINVAL > State.orchestrators[i].balance_LPT_pending:
            Util.log("Cannot transfer LPT, as the minimum value to leave behind is larger than the self-stake", 1)
        else:
            Util.log("{0} has {1:.2f} LPT pending stake > threshold of {2:.2f} LPT".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_LPT_pending, State.LPT_THRESHOLD), 2)
            Contract.doTransferBond(i)
            Contract.refreshStake(i)

        # Then check pending ETH balance
        if current_time < State.orchestrators[i].previous_ETH_refresh + State.WAIT_TIME_ETH_REFRESH:
            Util.log("(cached) {0}'s pending fees is {1:.4f} ETH. Refreshing in {2:.0f} seconds...".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_ETH_pending,State.WAIT_TIME_ETH_REFRESH - (current_time - State.orchestrators[i].previous_ETH_refresh)), 3)
        else:
            Contract.refreshFees(i)
            Contract.checkEthBalance(i)

        # Withdraw pending ETH if threshold is reached
        # Note that balance_ETH_pending only counts fees which can be withdrawn right now, see Contract.getClaimable
        if State.orchestrators[i].balance_ETH_pending < State.ETH_THRESHOLD:
            Util.log("{0} has {1:.4f} ETH in pending fees < threshold of {2:.4f} ETH".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_ETH_pending, State.ETH_THRESHOLD), 3)
        else:
            Util.log("{0} has {1:.4f} in ETH pending fees > threshold of {2:.4f} ETH, withdrawing fees...".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_ETH_pending, State.ETH_THRESHOLD), 2)
            Contract.doWithdrawFees(i)
            Contract.refreshFees(i)
            Contract.checkEthBalance(i)

        # Transfer ETH to receiver if threshold is reached
        if State.orchestrators[i].balance_ETH < State.ETH_THRESHOLD:
            Util.log("{0} has {1:.4f} ETH in their wallet < threshold of {2:.4f} ETH".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_ETH, State.ETH_THRESHOLD), 3)
        elif State.ETH_MINVAL > State.orchestrators[i].balance_ETH:
            Util.log("Cannot transfer ETH, as the minimum value to leave behind is larger than the balance", 1)
        else:
            Util.log("{0} has {1:.4f} in ETH pending fees > threshold of {2:.4f} ETH, sending some to {3}...".format(State.orchestrators[i].source_address, State.orchestrators[i].balance_ETH, State.ETH_THRESHOLD, State.orchestrators[i].target_address_ETH), 2)
            Contract.doSendFees(i)
            Contract.checkEthBalance(i)


# Now we have everything set up, endlessly loop
while True:
    current_time = datetime.now(timezone.utc).timestamp()
    if State.require_user_input or State.LOCK_INTERACTIVE:
        User.handleUserInput()
    else:
        # Main logic of refreshing cached variables and calling contract functions
        refreshState()
        # Sleep WAIT_TIME_IDLE seconds until next refresh 
        delay = State.WAIT_TIME_IDLE
        while delay > 0:
            # Exit early if we received a signal from the terminal
            if State.require_user_input:
                break
            Util.log("Sleeping for 10 seconds ({0} idle time left)".format(delay), 3)
            if (delay > 10):
                delay = delay - 10
                time.sleep(10)
            else:
                time.sleep(delay)
                delay = 0