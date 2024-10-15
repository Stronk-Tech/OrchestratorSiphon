# Any functions which requires reading/writing smart contracts gets dumped here
from datetime import datetime, timezone #< In order to update the timer for cached variables
import web3 #< Currency conversions
# Import our own libraries
from lib import Util


### Round refresh logic


"""
@brief Refreshes the current round number
"""
def refreshRound():
    global rounds_contract
    global current_round_num
    global previous_round_refresh
    try:
        this_round = rounds_contract.functions.currentRound().call()
        previous_round_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("Current round number is {0}".format(this_round))
        current_round_num = this_round
    except Exception as e:
        Util.log("Unable to refresh round number: {0}".format(e))

"""
@brief Refreshes the current round lock status
"""
def refreshLock():
    global rounds_contract
    global current_round_isLocked
    try:
        new_lock = rounds_contract.functions.current_round_isLocked().call()
        current_round_isLocked = new_lock
    except Exception as e:
        Util.log("Unable to refresh round lock status: {0}".format(e))

"""
@brief Refreshes the last round the orch called reward
@param idx: which Orch # in the set to check
"""
def refreshRewardRound(idx):
    global orchestrators
    global bonding_contract
    try:
        # getTranscoder       returns [lastRewardRound, rewardCut, feeShare, 
        #                              lastActiveStakeUpdateRound, activationRound, deactivationRound,
        #                              activeCumulativeRewards, cumulativeRewards, cumulativeFees,
        #                              lastFeeRound]
        orchestrator_info = bonding_contract.functions.getTranscoder(orchestrators[idx].source_checksum_address).call()
        orchestrators[idx].previous_reward_round = orchestrator_info[0]
        orchestrators[idx].previous_round_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("Latest reward round for {0} is {1}".format(orchestrators[idx].source_address, orchestrators[idx].previous_reward_round))
    except Exception as e:
        Util.log("Unable to refresh round lock status: {0}".format(e))


### Orch LPT logic


"""
@brief Refresh Delegator amount of LPT available for withdrawal
@param idx: which Orch # in the set to check
"""
def refreshStake(idx):
    global orchestrators
    global bonding_contract
    try:
        pending_lptu = bonding_contract.functions.pendingStake(orchestrators[idx].source_checksum_address, 99999).call()
        pending_lpt = web3.Web3.from_wei(pending_lptu, 'ether')
        orchestrators[idx].balance_LPT_pending = pending_lpt
        orchestrators[idx].previous_LPT_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("{0} currently has {1:.2f} LPT available for unstaking".format(orchestrators[idx].source_address, pending_lpt))
    except Exception as e:
        Util.log("Unable to refresh stake: '{0}'".format(e))

"""
@brief Transfers all but LPT_MINVAL LPT stake to the configured destination wallet
@param idx: which Orch # in the set to check
"""
def doTransferBond(idx):
    global orchestrators
    global LPT_MINVAL
    global bonding_contract
    global w3
    try:
        transfer_amount = web3.Web3.to_wei(float(orchestrators[idx].balance_LPT_pending) - LPT_MINVAL, 'ether')
        Util.log("Going to transfer {0} LPTU bond to {1}".format(transfer_amount, orchestrators[idx].receiver_address_LPT))
        # Build transaction info
        transaction_obj = bonding_contract.functions.transferBond(orchestrators[idx].receiver_checksum_address_LPT, transfer_amount,
            web3.constants.ADDRESS_ZERO, web3.constants.ADDRESS_ZERO, web3.constants.ADDRESS_ZERO,
            web3.constants.ADDRESS_ZERO).build_transaction(
            {
                "from": orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Transfer bond success.')
    except Exception as e:
        Util.log("Unable to transfer bond: {0}".format(e))

"""
@brief Calls reward for the Orchestrator
@param idx: which Orch # in the set to call reward for
"""
def doCallReward(idx):
    global orchestrators
    global bonding_contract
    global w3
    try:
        Util.log("Calling reward for {0}".format(orchestrators[idx].source_address))
        # Build transaction info
        transaction_obj = bonding_contract.functions.reward().build_transaction(
            {
                "from": orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Call to reward success.')
    except Exception as e:
        Util.log("Unable to call reward: {0}".format(e))


### Orchestrator ETH logic


"""
@brief Refreshes pending ETH fees
@param idx: which Orch # in the set to check
"""
def refreshFees(idx):
    global orchestrators
    global bonding_contract
    try:
        pending_wei = bonding_contract.functions.pendingFees(orchestrators[idx].source_checksum_address, 99999).call()
        pending_eth = web3.Web3.from_wei(pending_wei, 'ether')
        orchestrators[idx].balance_ETH_pending = pending_eth
        orchestrators[idx].previous_ETH_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("{0} has {1:.6f} ETH in pending fees".format(orchestrators[idx].source_address, pending_eth))
    except Exception as e:
        Util.log("Unable to refresh fees: '{0}'".format(e))

"""
@brief Withdraws all fees to the receiver wallet
@param idx: which Orch # in the send from
"""
def doWithdrawFees(idx):
    global orchestrators
    global bonding_contract
    global w3
    global WITHDRAW_TO_RECEIVER
    global ETH_MINVAL
    try:
        # We take a little bit off due to floating point inaccuracies causing tx's to fail
        transfer_amount = web3.Web3.to_wei(float(orchestrators[idx].balance_ETH_pending) - 0.00001, 'ether')
        receiver_address = orchestrators[idx].source_checksum_address
        if not WITHDRAW_TO_RECEIVER:
            Util.log("Withdrawing {0} WEI to {1}".format(transfer_amount, orchestrators[idx].source_address))
        elif orchestrators[idx].balance_ETH < ETH_MINVAL:
            Util.log("{0} has a balance of {1:.4f} ETH. Withdrawing fees to the Orch wallet to maintain the minimum balance of {2:.4f}".format(orchestrators[idx].source_address, orchestrators[idx].balance_ETH, ETH_MINVAL))
        else:
            receiver_address = orchestrators[idx].target_checksum_address_ETH
            Util.log("Withdrawing {0} WEI directly to receiver wallet {1}".format(transfer_amount, orchestrators[idx].target_address_ETH))
        # Build transaction info
        transaction_obj = bonding_contract.functions.withdrawFees(receiver_address, transfer_amount).build_transaction(
            {
                "from": orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Withdraw fees success.')
    except Exception as e:
        Util.log("Unable to withdraw fees: '{0}'".format(e))

"""
@brief Updates known ETH balance of the Orch
@param idx: which Orch # in the set to check
"""
def checkEthBalance(idx):
    global orchestrators
    global w3
    global ETH_WARN
    try:
        balance_wei = w3.eth.get_balance(orchestrators[idx].source_checksum_address)
        balance_ETH = web3.Web3.from_wei(balance_wei, 'ether')
        orchestrators[idx].balance_ETH = balance_ETH
        Util.log("{0} currently has {1:.4f} ETH in their wallet".format(orchestrators[idx].source_address, balance_ETH))
        if balance_ETH < ETH_WARN:
            Util.log("{0} should top up their ETH balance ASAP!".format(orchestrators[idx].source_address))
    except Exception as e:
        Util.log("Unable to get ETH balance: '{0}'".format(e))

"""
@brief Transfers all ETH minus ETH_MINVAL to the receiver wallet
@param idx: which Orch # in the set to use
"""
def doSendFees(idx):
    global orchestrators
    global w3
    global ETH_MINVAL
    try:
        transfer_amount = web3.Web3.to_wei(float(orchestrators[idx].balance_ETH) - ETH_MINVAL, 'ether')
        Util.log("Should transfer {0} wei".format(transfer_amount))
        # Build transaction info
        transaction_obj = {
            'from': orchestrators[idx].source_checksum_address,
            'to': orchestrators[idx].target_checksum_address_ETH,
            'value': transfer_amount,
            "nonce": w3.eth.get_transaction_count(orchestrators[idx].source_checksum_address),
            'gas': 300000,
            'maxFeePerGas': 2000000000,
            'maxPriorityFeePerGas': 1000000000,
            'chainId': 42161
        }

        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Transfer ETH success.')
    except Exception as e:
        Util.log("Unable to send ETH: {0}".format(e))
