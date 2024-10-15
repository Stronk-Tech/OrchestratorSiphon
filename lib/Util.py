# Contains all generic functions separate from the main logic
# These are shared between all libraries and the main script
from datetime import datetime #< Used to print the current time
import sys #< Used to flush STDOUT or exit
import os #< Check if a filepath is valid
import web3 #< Handling wallet addresses
# Import our own libraries
from lib import State

"""
@brief Logs `info` to the terminal with an attached datetime
"""
def log(info):
    print("[", datetime.now(), "] - ", info)
    sys.stdout.flush()

"""
@brief Returns a checksum version of a wallet to be used for contract calls
@param wallet: public key of a wallet
"""
def getChecksumAddr(wallet):
    try:
        parsed_wallet = web3.Web3.to_checksum_address(wallet.lower())
        return parsed_wallet
    except Exception as e:
        log("Fatal error: Unable to parse wallet address: {0}".format(e))
        sys.exit(1)

"""
@brief Checks if a string is a valid filepath
@param file_path: absolute/relative path on the filesystem
@return boolean: True if a valid file, else False
"""
def checkPath(file_path):
    if not isinstance(file_path, str):
        return False
    return os.path.isfile(file_path)

"""
@brief Overwrites the password file with an empty string
@param file_path: absolute/relative path to a text file
"""
def clearPassword(file_path):
    if not checkPath(file_path):
        return
    try:
        with open(file_path, 'w') as file:
            pass
        log('Clear password file success.')
    except Exception as e:
        log("WARNING: was not able to overwrite the password file: {0}".format(e))

"""
@brief Returns the private key of a wallet
@param keystore_path: absolute/relative path to a keystore file
@param password: the password itself or a absolute/relative path to a text file with the password
"""
def getPrivateKey(keystore_path, password):
    try:
        with open(keystore_path) as key_file:
            encrypted_key = key_file.read()
            if checkPath(password):
                with open(password) as password_file:
                    key_password = password_file.read()
                    return State.w3.eth.account.decrypt(encrypted_key, key_password.rstrip('\n'))
            else:
                return State.w3.eth.account.decrypt(encrypted_key, password)
    except Exception as e:
        log("Unable to decrypt key: {0}".format(e))
        return ""
