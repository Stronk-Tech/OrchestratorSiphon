# All classes and variables we want to share across files
import web3 #< Everything related to the keystore & smart contracts
import configparser #< Parse the .ini file
import os #< Used to get environment variables
import sys #< To exit the program
import json #< Parse JSON ABI file

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
current_round_is_locked = False
current_time = 0
orchestrators = []
require_user_input = False


### Define contracts


"""
@brief Returns a JSON object of ABI data
@param path: absolute/relative path to an ABI file
"""
def getABI(path):
    try:
        with open(path) as f:
            info_json = json.load(f)
            return info_json["abi"]
    except Exception as e:
        print("Fatal error: Unable to extract ABI data: {0}".format(e))
        sys.exit(1)

abi_bonding_manager = getABI("./BondingManagerTarget.json")
abi_rounds_manager = getABI("./RoundsManagerTarget.json")
# connect to L2 rpc provider
provider = web3.HTTPProvider(L2_RPC_PROVIDER)
w3 = web3.Web3(provider)
assert w3.is_connected()
# prepare contracts
bonding_contract = w3.eth.contract(address=BONDING_CONTRACT_ADDR, abi=abi_bonding_manager)
rounds_contract = w3.eth.contract(address=ROUNDS_CONTRACT_ADDR, abi=abi_rounds_manager)


