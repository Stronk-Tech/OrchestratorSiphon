# All classes and variables we want to share across files
# Also parses the config on initialisation
import configparser #< Parse the .ini file
import os #< Used to get environment variables & for resolving relative file paths


### Export path to be able to resolve the JSON and ini files correctly


# Determine root directory
SIPHON_ROOT = os.path.dirname(os.path.abspath(__file__))
# Remove subdir which venv's can add
if SIPHON_ROOT.endswith("/lib"):
    SIPHON_ROOT = os.path.dirname(SIPHON_ROOT)


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
config.read(os.path.join(SIPHON_ROOT, 'config.ini'))

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
# Gas
GAS_MAX_FEE_GWEI = float(os.getenv('SIPHON_GAS_MAX_FEE', config.get('gas', 'max_fee_gwei', fallback='2')))
GAS_HEADROOM = float(os.getenv('SIPHON_GAS_HEADROOM', config.get('gas', 'headroom', fallback='2')))
# RPC
L2_RPC_PROVIDER = os.getenv('SIPHON_RPC_L2', config['rpc']['l2'])
# Other
LOG_VERBOSITY = int(os.getenv('SIPHON_VERBOSITY', config['other']['verbosity']))
LOG_TIMESTAMPED = bool(os.getenv('SIPHON_TIMESTAMPED', config.getboolean('other', 'log_timestamped')))
LOCK_INTERACTIVE = bool = False  # Tracks if the program is locked into interactive mode

# Internal globals
previous_round_refresh = 0
current_round_num = 0
current_round_is_locked = False
current_time = 0
orchestrators = []
require_user_input = False
