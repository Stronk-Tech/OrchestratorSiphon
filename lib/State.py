# All classes and variables we want to share across files
import web3 #< Everything related to the keystore & smart contracts
import configparser #< Parse the .ini file
import os #< Used to get environment variables
# Import our own libraries
from lib import Util, Contract

### Config & Variables


# Turn config options into a nice object to work with later
class OrchConf:
  def __init__(self, key, pw, pub, eth_target, lpt_target):
    self._source_key = key
    self._source_password = pw
    self._source_address = pub
    self._target_address_eth = eth_target
    self._target_address_lpt = lpt_target

# Load config file
config = configparser.ConfigParser()
config.read('config.ini')

# For each keystore section, create a OrchConf object
KEYSTORE_CONFIGS = []
# If there's no environment variable set, read keystore config from .ini file
if os.getenv('KEYSTORE', "") == "":
    for section in config.sections():
        if section.startswith('keystore'):
            KEYSTORE_CONFIGS.append(
                OrchConf(
                    config[section]['keystore'],
                    config[section]['password'],
                    config[section]['source_address'],
                    config[section]['receiver_address_eth'],
                    config[section]['receiver_address_lpt']
                )
            )
else:
    # Else ignore keystore config - read all data from environment variables
    keystores = os.getenv('SIPHON_KEYSTORES', "")
    passwords = os.getenv('SIPHON_PASSWORDS', "")
    source_adresses = os.getenv('SIPHON_SOURCES', "")
    receiver_addresses_eth = os.getenv('SIPHON_TARGETS_ETH', "")
    receiver_addresses_lpt = os.getenv('SIPHON_TARGETS_LPT', "")
    for keystore, password, source_adress, receiver_address_eth, receiver_address_lpt in zip(keystores, passwords, source_adresses, receiver_addresses_eth, receiver_addresses_lpt):
            KEYSTORE_CONFIGS.append(
                OrchConf(
                    keystore,
                    password,
                    source_adress,
                    receiver_address_eth,
                    receiver_address_lpt
                )
            )
# Features
WITHDRAW_TO_RECEIVER = bool(os.getenv('SIPHON_WITHDRAW_TO_RECEIVER', config.getboolean('features', 'withdraw_to_receiver')))
CLEAR_PASSWORD = bool(os.getenv('SIPHON_CLEAR_PASSWORD', config.getboolean('features', 'clear_password')))
# Thresholds
LPT_THRESHOLD = float(os.getenv('SIPHON_LPT_THRESHOLD', config['thresholds']['lpt_threshold']))
ETH_THRESHOLD = float(os.getenv('SIPHON_ETH_THRESHOLD', config['thresholds']['eth_threshold']))
ETH_MINVAL = float(os.getenv('SIPHON_ETH_MINVAL', config['thresholds']['eth_minval']))
ETH_WARN = float(os.getenv('SIPHON_ETH_WARN', config['thresholds']['eth_warn']))
LPT_MINVAL = float(os.getenv('SIPHON_LPT_MINVAL', config['thresholds']['lpt_minval']))
# Timers
WAIT_TIME_ROUND_REFRESH = float(os.getenv('SIPHON_CACHE_ROUNDS', config['timers']['cache_round_refresh']))
WAIT_TIME_LPT_REFRESH = float(os.getenv('SIPHNO_CACHE_LPT', config['timers']['cache_pending_lpt']))
WAIT_TIME_ETH_REFRESH = float(os.getenv('SIPHNO_CACHE_ETH', config['timers']['cache_pending_eth']))
WAIT_TIME_IDLE = float(os.getenv('SIPHNO_WAIT_IDLE', config['timers']['wait_idle']))
# RPC
L2_RPC_PROVIDER = os.getenv('SIPHON_RPC_L2', config['rpc']['l2'])

# Internal globals - Probably don't touch these
BONDING_CONTRACT_ADDR = '0x35Bcf3c30594191d53231E4FF333E8A770453e40'
ROUNDS_CONTRACT_ADDR = '0xdd6f56DcC28D3F5f27084381fE8Df634985cc39f'
previous_round_refresh = 0
current_round_num = 0
current_round_isLocked = False
current_time = 0
orchestrators = []
require_user_input = False


### Define contracts


abi_bonding_manager = Util.getABI("./BondingManagerTarget.json")
abi_rounds_manager = Util.getABI("./RoundsManagerTarget.json")
# connect to L2 rpc provider
provider = web3.HTTPProvider(L2_RPC_PROVIDER)
w3 = web3.Web3(provider)
assert w3.is_connected()
# prepare contracts
bonding_contract = w3.eth.contract(address=BONDING_CONTRACT_ADDR, abi=abi_bonding_manager)
rounds_contract = w3.eth.contract(address=ROUNDS_CONTRACT_ADDR, abi=abi_rounds_manager)


"""
@brief Checks all Orchestrators if any cached data needs refreshing or contracts need calling
"""
def refreshState():
    if require_user_input:
        return
    # Check for round updates
    if current_time < previous_round_refresh + WAIT_TIME_ROUND_REFRESH:
        if current_round_isLocked:
            Util.log("(cached) Round status: round {0} (locked). Refreshing in {1:.0f} seconds...".format(current_round_num, WAIT_TIME_ROUND_REFRESH - (current_time - previous_round_refresh)))
        else:
            Util.log("(cached) Round status: round {0} (unlocked). Refreshing in {1:.0f} seconds...".format(current_round_num, WAIT_TIME_ROUND_REFRESH - (current_time - previous_round_refresh)))
    else:
        Contract.refreshRound()
        Contract.refreshLock()

    # Now check each Orch keystore for expired cached values and do stuff
    for i in range(len(orchestrators)):
        Util.log("Refreshing Orchestrator '{0}'".format(orchestrators[i].source_address))

        # First check pending LPT
        if current_time < orchestrators[i].previous_LPT_refresh + WAIT_TIME_LPT_REFRESH:
            Util.log("(cached) {0}'s pending stake is {1:.2f} LPT. Refreshing in {2:.0f} seconds...".format(orchestrators[i].source_address, orchestrators[i].balance_LPT_pending, WAIT_TIME_LPT_REFRESH - (current_time - orchestrators[i].previous_LPT_refresh)))
        else:
            Contract.refreshStake(i)

        # Transfer pending LPT at the end of round if threshold is reached
        if orchestrators[i].balance_LPT_pending < LPT_THRESHOLD:
            Util.log("{0} has {1:.2f} LPT in pending stake < threshold of {2:.2f} LPT".format(orchestrators[i].source_address, orchestrators[i].balance_LPT_pending, LPT_THRESHOLD))
        else:
            Util.log("{0} has {1:.2f} LPT pending stake > threshold of {2:.2f} LPT".format(orchestrators[i].source_address, orchestrators[i].balance_LPT_pending, LPT_THRESHOLD))
            if LPT_MINVAL > orchestrators[i].balance_LPT_pending:
                Util.log("Cannot transfer LPT, as the minimum value to leave behind is larger than the self-stake")
            elif current_round_isLocked:
                Contract.doTransferBond(i)
                Contract.refreshStake(i)
            else:
                Util.log("Waiting for round to be locked before transferring bond")

        # Then check pending ETH balance
        if current_time < orchestrators[i].previous_ETH_refresh + WAIT_TIME_ETH_REFRESH:
            Util.log("(cached) {0}'s pending fees is {1:.4f} ETH. Refreshing in {2:.0f} seconds...".format(orchestrators[i].source_address, orchestrators[i].balance_ETH_pending, WAIT_TIME_ETH_REFRESH - (current_time - orchestrators[i].previous_ETH_refresh)))
        else:
            Contract.refreshFees(i)
            Contract.checkEthBalance(i)

        # Withdraw pending ETH if threshold is reached 
        if orchestrators[i].balance_ETH_pending < ETH_THRESHOLD:
            Util.log("{0} has {1:.4f} ETH in pending fees < threshold of {2:.4f} ETH".format(orchestrators[i].source_address, orchestrators[i].balance_ETH_pending, ETH_THRESHOLD))
        else:
            Util.log("{0} has {1:.4f} in ETH pending fees > threshold of {2:.4f} ETH, withdrawing fees...".format(orchestrators[i].source_address, orchestrators[i].balance_ETH_pending, ETH_THRESHOLD))
            Contract.doWithdrawFees(i)
            Contract.refreshFees(i)
            Contract.checkEthBalance(i)

        # Transfer ETH to receiver if threshold is reached
        if orchestrators[i].balance_ETH < ETH_THRESHOLD:
            Util.log("{0} has {1:.4f} ETH in their wallet < threshold of {2:.4f} ETH".format(orchestrators[i].source_address, orchestrators[i].balance_ETH, ETH_THRESHOLD))
        elif ETH_MINVAL > orchestrators[i].balance_ETH:
            Util.log("Cannot transfer ETH, as the minimum value to leave behind is larger than the balance")
        else:
            Util.log("{0} has {1:.4f} in ETH pending fees > threshold of {2:.4f} ETH, sending some to {3}...".format(orchestrators[i].source_address, orchestrators[i].balance_ETH, ETH_THRESHOLD, orchestrators[i].target_address_ETH))
            Contract.doSendFees(i)
            Contract.checkEthBalance(i)

        # Lastly: check if we need to call reward
        
        # We can continue immediately if the latest round has not changed
        if orchestrators[i].previous_reward_round >= current_round_num:
            Util.log("Done for '{0}' as they have already called reward this round".format(orchestrators[i].source_address))
            continue

        # Refresh Orch reward round
        if current_time < orchestrators[i].previous_round_refresh + WAIT_TIME_ROUND_REFRESH:
            Util.log("(cached) {0}'s last reward round is {1}. Refreshing in {2:.0f} seconds...".format(orchestrators[i].source_address, orchestrators[i].previous_reward_round, WAIT_TIME_ROUND_REFRESH - (current_time - orchestrators[i].previous_round_refresh)))
        else:
            Contract.refreshRewardRound(i)

        # Call reward
        if orchestrators[i].previous_reward_round < current_round_num:
            Util.log("Calling reward for {0}...".format(orchestrators[i].source_address))
            Contract.doCallReward(i)
            Contract.refreshRewardRound(i)
            Contract.refreshStake(i)
        else:
            Util.log("{0} has already called reward in round {1}".format(orchestrators[i].source_address, current_round_num))

