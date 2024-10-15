# Any functions which requires reading/writing smart contracts gets dumped here
from datetime import datetime, timezone #< In order to update the timer for cached variables
import web3 #< Currency conversions
# Import our own libraries
from lib import Util, State


### Round refresh logic


"""
@brief Refreshes the current round number
"""
def refreshRound():
    try:
        this_round = State.rounds_contract.functions.currentRound().call()
        State.previous_round_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("Current round number is {0}".format(this_round))
        State.current_round_num = this_round
    except Exception as e:
        Util.log("Unable to refresh round number: {0}".format(e))

"""
@brief Refreshes the current round lock status
"""
def refreshLock():
    try:
        new_lock = State.rounds_contract.functions.currentRoundLocked().call()
        State.current_round_is_locked = new_lock
    except Exception as e:
        Util.log("Unable to refresh round lock status: {0}".format(e))

"""
@brief Refreshes the last round the orch called reward
@param idx: which Orch # in the set to check
"""
def refreshRewardRound(idx):
    try:
        # getTranscoder       returns [lastRewardRound, rewardCut, feeShare, 
        #                              lastActiveStakeUpdateRound, activationRound, deactivationRound,
        #                              activeCumulativeRewards, cumulativeRewards, cumulativeFees,
        #                              lastFeeRound]
        orchestrator_info = State.bonding_contract.functions.getTranscoder(State.orchestrators[idx].source_checksum_address).call()
        State.orchestrators[idx].previous_reward_round = orchestrator_info[0]
        State.orchestrators[idx].previous_round_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("Latest reward round for {0} is {1}".format(State.orchestrators[idx].source_address, State.orchestrators[idx].previous_reward_round))
    except Exception as e:
        Util.log("Unable to refresh round lock status: {0}".format(e))


### Orch LPT logic


"""
@brief Refresh Delegator amount of LPT available for withdrawal
@param idx: which Orch # in the set to check
"""
def refreshStake(idx):
    try:
        pending_lptu = State.bonding_contract.functions.pendingStake(State.orchestrators[idx].source_checksum_address, 99999).call()
        pending_lpt = web3.Web3.from_wei(pending_lptu, 'ether')
        State.orchestrators[idx].balance_LPT_pending = pending_lpt
        State.orchestrators[idx].previous_LPT_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("{0} currently has {1:.2f} LPT available for unstaking".format(State.orchestrators[idx].source_address, pending_lpt))
    except Exception as e:
        Util.log("Unable to refresh stake: '{0}'".format(e))

"""
@brief Transfers all but LPT_MINVAL LPT stake to the configured destination wallet
@param idx: which Orch # in the set to check
"""
def doTransferBond(idx):
    try:
        transfer_amount = web3.Web3.to_wei(float(State.orchestrators[idx].balance_LPT_pending) - State.LPT_MINVAL, 'ether')
        Util.log("Going to transfer {0} LPTU bond to {1}".format(transfer_amount, State.orchestrators[idx].receiver_address_LPT))
        # Build transaction info
        transaction_obj = State.bonding_contract.functions.transferBond(State.orchestrators[idx].receiver_checksum_address_LPT, transfer_amount,
            web3.constants.ADDRESS_ZERO, web3.constants.ADDRESS_ZERO, web3.constants.ADDRESS_ZERO,
            web3.constants.ADDRESS_ZERO).build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": State.w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = State.w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = State.w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = State.w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Transfer bond success.')
    except Exception as e:
        Util.log("Unable to transfer bond: {0}".format(e))

"""
@brief Calls reward for the Orchestrator
@param idx: which Orch # in the set to call reward for
"""
def doCallReward(idx):
    try:
        Util.log("Calling reward for {0}".format(State.orchestrators[idx].source_address))
        # Build transaction info
        transaction_obj = State.bonding_contract.functions.reward().build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": State.w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = State.w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = State.w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = State.w3.eth.wait_for_transaction_receipt(transaction_hash)
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
    try:
        pending_wei = State.bonding_contract.functions.pendingFees(State.orchestrators[idx].source_checksum_address, 99999).call()
        pending_eth = web3.Web3.from_wei(pending_wei, 'ether')
        State.orchestrators[idx].balance_ETH_pending = pending_eth
        State.orchestrators[idx].previous_ETH_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("{0} has {1:.6f} ETH in pending fees".format(State.orchestrators[idx].source_address, pending_eth))
    except Exception as e:
        Util.log("Unable to refresh fees: '{0}'".format(e))

"""
@brief Withdraws all fees to the receiver wallet
@param idx: which Orch # in the send from
"""
def doWithdrawFees(idx):
    try:
        # We take a little bit off due to floating point inaccuracies causing tx's to fail
        transfer_amount = web3.Web3.to_wei(float(State.orchestrators[idx].balance_ETH_pending) - 0.00001, 'ether')
        receiver_address = State.orchestrators[idx].source_checksum_address
        if not State.WITHDRAW_TO_RECEIVER:
            Util.log("Withdrawing {0} WEI to {1}".format(transfer_amount, State.orchestrators[idx].source_address))
        elif State.orchestrators[idx].balance_ETH < State.ETH_MINVAL:
            Util.log("{0} has a balance of {1:.4f} ETH. Withdrawing fees to the Orch wallet to maintain the minimum balance of {2:.4f}".format(State.orchestrators[idx].source_address, State.orchestrators[idx].balance_ETH, State.ETH_MINVAL))
        else:
            receiver_address = State.orchestrators[idx].target_checksum_address_ETH
            Util.log("Withdrawing {0} WEI directly to receiver wallet {1}".format(transfer_amount, State.orchestrators[idx].target_address_ETH))
        # Build transaction info
        transaction_obj = State.bonding_contract.functions.withdrawFees(receiver_address, transfer_amount).build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": State.w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = State.w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = State.w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = State.w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Withdraw fees success.')
    except Exception as e:
        Util.log("Unable to withdraw fees: '{0}'".format(e))

"""
@brief Updates known ETH balance of the Orch
@param idx: which Orch # in the set to check
"""
def checkEthBalance(idx):
    try:
        balance_wei = State.w3.eth.get_balance(State.orchestrators[idx].source_checksum_address)
        balance_ETH = web3.Web3.from_wei(balance_wei, 'ether')
        State.orchestrators[idx].balance_ETH = balance_ETH
        Util.log("{0} currently has {1:.4f} ETH in their wallet".format(State.orchestrators[idx].source_address, balance_ETH))
        if balance_ETH < State.ETH_WARN:
            Util.log("{0} should top up their ETH balance ASAP!".format(State.orchestrators[idx].source_address))
    except Exception as e:
        Util.log("Unable to get ETH balance: '{0}'".format(e))

"""
@brief Transfers all ETH minus ETH_MINVAL to the receiver wallet
@param idx: which Orch # in the set to use
"""
def doSendFees(idx):
    try:
        transfer_amount = web3.Web3.to_wei(float(State.orchestrators[idx].balance_ETH) - State.ETH_MINVAL, 'ether')
        Util.log("Should transfer {0} wei".format(transfer_amount))
        # Build transaction info
        transaction_obj = {
            'from': State.orchestrators[idx].source_checksum_address,
            'to': State.orchestrators[idx].target_checksum_address_ETH,
            'value': transfer_amount,
            "nonce": State.w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address),
            'gas': 300000,
            'maxFeePerGas': 2000000000,
            'maxPriorityFeePerGas': 1000000000,
            'chainId': 42161
        }

        # Sign and initiate transaction
        signed_transaction = State.w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = State.w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()))
        # Wait for transaction to be confirmed
        receipt = State.w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Transfer ETH success.')
    except Exception as e:
        Util.log("Unable to send ETH: {0}".format(e))
