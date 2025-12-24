# Any functions which requires reading/writing smart contracts gets dumped here
# Also connects to the RPC provider and holds accessors to the smart contracts
from datetime import datetime, timezone #< In order to update the timer for cached variables
import web3 #< Currency conversions
import sys #< To exit the program
import json #< Parse JSON ABI file
import re #< Parse proposal description
import time #< For rate limiting in chunked queries
# Import our own libraries
from lib import Util, State


BONDING_CONTRACT_ADDR = '0x35Bcf3c30594191d53231E4FF333E8A770453e40'
ROUNDS_CONTRACT_ADDR = '0xdd6f56DcC28D3F5f27084381fE8Df634985cc39f'
GOVERNOR_CONTRACT_ADDR = '0xcFE4E2879B786C3aa075813F0E364bb5acCb6aa0'

# Proposal states (OpenZeppelin IGovernor)
PROPOSAL_STATE_PENDING = 0
PROPOSAL_STATE_ACTIVE = 1
PROPOSAL_STATE_CANCELED = 2
PROPOSAL_STATE_DEFEATED = 3
PROPOSAL_STATE_SUCCEEDED = 4
PROPOSAL_STATE_QUEUED = 5
PROPOSAL_STATE_EXPIRED = 6
PROPOSAL_STATE_EXECUTED = 7

PROPOSAL_STATE_NAMES = {
    0: "Pending",
    1: "Active",
    2: "Canceled",
    3: "Defeated",
    4: "Succeeded",
    5: "Queued",
    6: "Expired",
    7: "Executed"
}


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
        Util.log("Fatal error: Unable to extract ABI data: {0}".format(e), 1)
        sys.exit(1)

abi_bonding_manager = getABI(State.SIPHON_ROOT + "/contracts/BondingManager.json")
abi_rounds_manager = getABI(State.SIPHON_ROOT + "/contracts/RoundsManager.json")
treasury_manager = getABI(State.SIPHON_ROOT + "/contracts/LivepeerGovernor.json")
# connect to L2 rpc provider
provider = web3.HTTPProvider(State.L2_RPC_PROVIDER)
w3 = web3.Web3(provider)
assert w3.is_connected()
# prepare contracts
bonding_contract = w3.eth.contract(address=BONDING_CONTRACT_ADDR, abi=abi_bonding_manager)
rounds_contract = w3.eth.contract(address=ROUNDS_CONTRACT_ADDR, abi=abi_rounds_manager)
treasury_contract = w3.eth.contract(address=GOVERNOR_CONTRACT_ADDR, abi=treasury_manager)


### Governance & Treasury logic


def printProgressBar(current, total, prefix='', length=30, extra=''):
    """Print a progress bar to stdout with optional extra info."""
    percent = current / total if total > 0 else 1
    filled = int(length * percent)
    bar = '█' * filled + '░' * (length - filled)
    print(f'\r{prefix} |{bar}| {percent*100:.1f}% {extra}', end='', flush=True)
    if current >= total:
        print()  # Newline when done


def getLogsInChunks(event, from_block, to_block):
    """
    Query event logs with adaptive block range and rate limiting.
    - Auto-discovers max block range (starts large, halves on error)
    - Auto-adjusts request rate (slows on rate limit)
    """
    all_logs = []
    current = from_block

    # Adaptive parameters - once reduced, stays reduced
    chunk_size = 500000  # Start optimistic (500k blocks)
    min_chunk = 1000     # Don't go below 1k
    delay = 0.01         # Start fast (100 req/s)
    max_delay = 0.5      # Max 2 req/s if heavily rate limited

    total_blocks = to_block - from_block
    retries = 0
    max_retries = 3

    while current <= to_block:
        end = min(current + chunk_size - 1, to_block)
        try:
            logs = event.get_logs(from_block=current, to_block=end)
            all_logs.extend(logs)
            retries = 0  # Reset on success

            # Update progress bar with details
            progress = current - from_block
            rate = 1 / delay if delay > 0 else 100
            extra = f"[{current:,}-{end:,}] chunk={chunk_size:,} rate={rate:.0f}/s"
            printProgressBar(progress, total_blocks, prefix='Scanning', extra=extra)

            current = end + 1
            time.sleep(delay)

        except Exception as e:
            # Get full error details
            error_type = type(e).__name__
            error_msg = str(e)
            error_str = error_msg.lower()

            # If exception has nested cause, get that too
            if hasattr(e, '__cause__') and e.__cause__:
                error_msg = f"{error_msg} | Cause: {e.__cause__}"
            if hasattr(e, 'args') and e.args:
                error_msg = f"{error_type}: {e.args}"

            # Clear progress bar line before logging errors
            print()

            # Timeout / temporary error - just retry (check first!)
            if any(x in error_str for x in ['timeout', 'deadline', 'connection']):
                Util.log("Timeout on blocks {0}-{1}, retrying: {2}".format(current, end, error_msg), 2)
                time.sleep(1)
                continue  # Retry same range

            # Rate limited - slow down (permanently)
            if any(x in error_str for x in ['rate', '429', 'too many requests']):
                delay = min(max_delay, delay * 2)
                Util.log("Rate limited, slowing to {0:.2f}s delay: {1}".format(delay, error_msg), 2)
                time.sleep(delay)
                continue  # Retry

            # Block range too large - halve it (permanently)
            if any(x in error_str for x in ['range', 'limit', '422', 'block', '10000']):
                if chunk_size > min_chunk:
                    chunk_size = chunk_size // 2
                    Util.log("Reducing chunk size to {0} blocks: {1}".format(chunk_size, error_msg), 2)
                    continue  # Retry same range with smaller chunk

            # Other error - retry up to max_retries, then skip
            retries += 1
            if retries <= max_retries:
                Util.log("Error querying blocks {0}-{1} (retry {2}/{3}): {4}".format(
                    current, end, retries, max_retries, error_msg), 1)
                time.sleep(1)
                continue
            else:
                Util.log("Giving up on blocks {0}-{1} after {2} retries: {3}".format(
                    current, end, max_retries, error_msg), 1)
                retries = 0
                current = end + 1
                time.sleep(0.5)

    # Final progress
    printProgressBar(total_blocks, total_blocks, prefix='Scanning', extra=f"Done! Found {len(all_logs)} events")
    return all_logs


def getProposalState(proposalId):
    """Get current state of a proposal (1 = Active)."""
    try:
        return treasury_contract.functions.state(proposalId).call()
    except Exception as e:
        Util.log("Unable to get proposal state: {0}".format(e), 1)
        return -1


def getVotingWindow():
    """
    Get the block range where active proposals can exist.
    Livepeer Governor uses rounds. roundLength is in L1 blocks (~12s each).
    We need to convert to L2 blocks (~0.25s each) for searching.
    """
    try:
        voting_delay = treasury_contract.functions.votingDelay().call()
        voting_period = treasury_contract.functions.votingPeriod().call()
        round_length_l1 = rounds_contract.functions.roundLength().call()

        # Convert L1 blocks to L2 blocks (L1 ~12s, L2 ~0.25s)
        l1_to_l2_ratio = 48  # 12s / 0.25s = 48 L2 blocks per L1 block
        round_length_l2 = round_length_l1 * l1_to_l2_ratio

        total_rounds = voting_delay + voting_period
        total_blocks = total_rounds * round_length_l2

        Util.log("Voting window: {0} rounds ({1} delay + {2} period) = {3} L2 blocks".format(
            total_rounds, voting_delay, voting_period, total_blocks), 2)
        return total_blocks
    except Exception as e:
        Util.log("Could not get voting parameters: {0}".format(e), 1)
        # Fallback: ~2 weeks on Arbitrum
        return 5_000_000


"""
@brief Returns all currently ACTIVE governance proposals
"""
def getProposals():
    try:
        current_block = w3.eth.block_number

        # Get voting window from contract (votingDelay + votingPeriod)
        voting_window = getVotingWindow()
        buffer_blocks = 50000  # Small buffer for safety
        from_block = max(0, current_block - voting_window - buffer_blocks)

        Util.log("Searching for proposals from block {0} to {1}".format(from_block, current_block), 2)

        # Query in adaptive chunks
        raw_proposals = getLogsInChunks(
            treasury_contract.events.ProposalCreated(),
            from_block,
            current_block
        )

        if not raw_proposals:
            Util.log("No proposals found in search range", 2)
            return []

        # Filter for ACTIVE proposals only
        Util.log("Found {0} proposals, checking states...".format(len(raw_proposals)), 2)
        active_proposals = []
        for proposal in raw_proposals:
            proposal_id = proposal.args.proposalId
            state = getProposalState(proposal_id)
            state_name = PROPOSAL_STATE_NAMES.get(state, f"Unknown({state})")
            title_and_body = proposal.args.description.split("\n")
            title = re.sub(r'^#+\s*', "", title_and_body[0])

            Util.log("Proposal '{0}' state: {1}".format(title[:50], state_name), 2)

            if state == PROPOSAL_STATE_ACTIVE:
                active_proposals.append({
                    "proposalId": proposal_id,
                    "proposer": proposal.args.proposer,
                    "targets": proposal.args.targets,
                    "voteStart": proposal.args.voteStart,
                    "voteEnd": proposal.args.voteEnd,
                    "title": title
                })

        Util.log("Found {0} active proposals".format(len(active_proposals)), 2)
        return active_proposals

    except Exception as e:
        Util.log("Unable to retrieve treasury proposals: {0}".format(e), 1)
        return []

"""
@brief Returns current vote counters
"""
def getVotes(proposalId):
    try:
        votes = []
        rawVotes = treasury_contract.functions.proposalVotes(proposalId).call()
        for vote in rawVotes:
            votes.append(web3.Web3.from_wei(vote, 'ether'))
        return votes
    except Exception as e:
        Util.log("Unable to retrieve votes: '{0}'".format(e), 1)

"""
@brief Checks whether the wallet has already voted
"""
def hasVoted(proposalId, address):
    try:
        return treasury_contract.functions.hasVoted(proposalId, address).call()
    except Exception as e:
        Util.log("Unable to check for voting status: '{0}'".format(e), 1)

"""
@brief Checks whether the wallet has already voted
"""
def doCastVote(idx, proposalId, value):
    try:
        # Build transaction info
        transaction_obj = treasury_contract.functions.castVote(proposalId, value).build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()), 2)
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Voted successfully', 2)
    except Exception as e:
        Util.log("Unable to vote: '{0}'".format(e), 1)

"""
@brief Checks whether the wallet has already voted
"""
def doCastVoteWithReason(idx, proposalId, value, reason):
    try:
        # Build transaction info
        transaction_obj = treasury_contract.functions.castVoteWithReason(proposalId, value, reason).build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()), 2)
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Voted successfully', 2)
    except Exception as e:
        Util.log("Unable to vote: '{0}'".format(e), 1)


### Round refresh logic


"""
@brief Refreshes the current round number
"""
def refreshRound():
    try:
        this_round = rounds_contract.functions.currentRound().call()
        State.previous_round_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("Current round number is {0}".format(this_round), 2)
        State.current_round_num = this_round
    except Exception as e:
        Util.log("Unable to refresh round number: {0}".format(e), 1)

"""
@brief Refreshes the current round lock status
"""
def refreshLock():
    try:
        new_lock = rounds_contract.functions.currentRoundLocked().call()
        Util.log("Current round lock status is {0}".format(new_lock), 2)
        State.current_round_is_locked = new_lock
    except Exception as e:
        Util.log("Unable to refresh round lock status: {0}".format(e), 1)

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
        orchestrator_info = bonding_contract.functions.getTranscoder(State.orchestrators[idx].source_checksum_address).call()
        State.orchestrators[idx].previous_reward_round = orchestrator_info[0]
        State.orchestrators[idx].previous_round_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("Latest reward round for {0} is {1}".format(State.orchestrators[idx].source_address, State.orchestrators[idx].previous_reward_round), 2)
    except Exception as e:
        Util.log("Unable to refresh round lock status: {0}".format(e), 1)


### Orch LPT logic


"""
@brief Refresh Delegator amount of LPT available for withdrawal
@param idx: which Orch # in the set to check
"""
def refreshStake(idx):
    try:
        pending_lptu = bonding_contract.functions.pendingStake(State.orchestrators[idx].source_checksum_address, 99999).call()
        pending_lpt = web3.Web3.from_wei(pending_lptu, 'ether')
        State.orchestrators[idx].balance_LPT_pending = pending_lpt
        State.orchestrators[idx].previous_LPT_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("{0} currently has {1:.2f} LPT available for unstaking".format(State.orchestrators[idx].source_address, pending_lpt), 2)
    except Exception as e:
        Util.log("Unable to refresh stake: '{0}'".format(e), 1)

"""
@brief Transfers all but LPT_MINVAL LPT stake to the configured destination wallet
@param idx: which Orch # in the set to check
"""
def doTransferBond(idx):
    try:
        transfer_amount = web3.Web3.to_wei(float(State.orchestrators[idx].balance_LPT_pending) - State.LPT_MINVAL, 'ether')
        Util.log("Going to transfer {0} LPTU bond to {1}".format(transfer_amount, State.orchestrators[idx].receiver_address_LPT), 2)
        # Build transaction info
        transaction_obj = bonding_contract.functions.transferBond(State.orchestrators[idx].receiver_checksum_address_LPT, transfer_amount,
            web3.constants.ADDRESS_ZERO, web3.constants.ADDRESS_ZERO, web3.constants.ADDRESS_ZERO,
            web3.constants.ADDRESS_ZERO).build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()), 2)
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Transfer bond success.', 2)
    except Exception as e:
        Util.log("Unable to transfer bond: {0}".format(e), 1)

"""
@brief Calls reward for the Orchestrator
@param idx: which Orch # in the set to call reward for
"""
def doCallReward(idx):
    try:
        Util.log("Calling reward for {0}".format(State.orchestrators[idx].source_address), 2)
        # Build transaction info
        transaction_obj = bonding_contract.functions.reward().build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()), 2)
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Call to reward success.', 2)
    except Exception as e:
        Util.log("Unable to call reward: {0}".format(e), 1)

"""
@brief Sets commission rates as a transcoder
@param idx: which Orch # in the set to set rates for
@param reward_percent_to_keep: % of rewards to keep as orchestrator (e.g., 30 for 30%)
@param fee_percent_to_keep: % of fees to keep as orchestrator (e.g., 30 for 30%)
"""
def doTranscoder(idx, reward_percent_to_keep, fee_percent_to_keep):
    try:
        # Convert percentages to the format expected by the smart contract
        # rewardCut: % of rewards orchestrator keeps (multiply by 10000 for precision)
        reward_cut = int(reward_percent_to_keep * 10000)
        # feeShare: % of fees that go to delegators (100% - orchestrator's %)
        fee_share = int((100 - fee_percent_to_keep) * 10000)

        Util.log("Setting transcoder rates for {0}: keeping {1}% of rewards, keeping {2}% of fees".format(
            State.orchestrators[idx].source_address, reward_percent_to_keep, fee_percent_to_keep), 2)
        Util.log("Contract parameters: rewardCut={0}, feeShare={1}".format(reward_cut, fee_share), 2)

        # Build transaction info
        transaction_obj = bonding_contract.functions.transcoder(reward_cut, fee_share).build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()), 2)
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Transcoder rates set successfully', 2)
    except Exception as e:
        Util.log("Unable to set transcoder rates: {0}".format(e), 1)


### Orchestrator ETH logic


"""
@brief Refreshes pending ETH fees
@param idx: which Orch # in the set to check
"""
def refreshFees(idx):
    try:
        pending_wei = bonding_contract.functions.pendingFees(State.orchestrators[idx].source_checksum_address, 99999).call()
        pending_eth = web3.Web3.from_wei(pending_wei, 'ether')
        State.orchestrators[idx].balance_ETH_pending = pending_eth
        State.orchestrators[idx].previous_ETH_refresh = datetime.now(timezone.utc).timestamp()
        Util.log("{0} has {1:.6f} ETH in pending fees".format(State.orchestrators[idx].source_address, pending_eth), 2)
    except Exception as e:
        Util.log("Unable to refresh fees: '{0}'".format(e), 1)

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
            Util.log("Withdrawing {0} WEI to {1}".format(transfer_amount, State.orchestrators[idx].source_address), 2)
        elif State.orchestrators[idx].balance_ETH < State.ETH_MINVAL:
            Util.log("{0} has a balance of {1:.4f} ETH. Withdrawing fees to the Orch wallet to maintain the minimum balance of {2:.4f}".format(State.orchestrators[idx].source_address, State.orchestrators[idx].balance_ETH, State.ETH_MINVAL), 2)
        else:
            receiver_address = State.orchestrators[idx].target_checksum_address_ETH
            Util.log("Withdrawing {0} WEI directly to receiver wallet {1}".format(transfer_amount, State.orchestrators[idx].target_address_ETH), 2)
        # Build transaction info
        transaction_obj = bonding_contract.functions.withdrawFees(receiver_address, transfer_amount).build_transaction(
            {
                "from": State.orchestrators[idx].source_checksum_address,
                'maxFeePerGas': 2000000000,
                'maxPriorityFeePerGas': 1000000000,
                "nonce": w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address)
            }
        )
        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()), 2)
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Withdraw fees success.', 2)
    except Exception as e:
        Util.log("Unable to withdraw fees: '{0}'".format(e), 1)

"""
@brief Updates known ETH balance of the Orch
@param idx: which Orch # in the set to check
"""
def checkEthBalance(idx):
    try:
        balance_wei = w3.eth.get_balance(State.orchestrators[idx].source_checksum_address)
        balance_ETH = web3.Web3.from_wei(balance_wei, 'ether')
        State.orchestrators[idx].balance_ETH = balance_ETH
        Util.log("{0} currently has {1:.4f} ETH in their wallet".format(State.orchestrators[idx].source_address, balance_ETH), 2)
        if balance_ETH < State.ETH_WARN:
            Util.log("{0} should top up their ETH balance ASAP!".format(State.orchestrators[idx].source_address), 1)
    except Exception as e:
        Util.log("Unable to get ETH balance: '{0}'".format(e), 1)

"""
@brief Transfers all ETH minus ETH_MINVAL to the receiver wallet
@param idx: which Orch # in the set to use
"""
def doSendFees(idx):
    try:
        transfer_amount = web3.Web3.to_wei(float(State.orchestrators[idx].balance_ETH) - State.ETH_MINVAL, 'ether')
        Util.log("Should transfer {0} wei to {1}".format(transfer_amount, State.orchestrators[idx].target_checksum_address_ETH), 2)
        # Build transaction info
        transaction_obj = {
            'from': State.orchestrators[idx].source_checksum_address,
            'to': State.orchestrators[idx].target_checksum_address_ETH,
            'value': transfer_amount,
            "nonce": w3.eth.get_transaction_count(State.orchestrators[idx].source_checksum_address),
            'gas': 300000,
            'maxFeePerGas': 2000000000,
            'maxPriorityFeePerGas': 1000000000,
            'chainId': 42161
        }

        # Sign and initiate transaction
        signed_transaction = w3.eth.account.sign_transaction(transaction_obj, State.orchestrators[idx].source_private_key)
        transaction_hash = w3.eth.send_raw_transaction(signed_transaction.raw_transaction)
        Util.log("Initiated transaction with hash {0}".format(transaction_hash.hex()), 2)
        # Wait for transaction to be confirmed
        receipt = w3.eth.wait_for_transaction_receipt(transaction_hash)
        # Util.log("Completed transaction {0}".format(receipt))
        Util.log('Transfer ETH success.', 2)
    except Exception as e:
        Util.log("Unable to send ETH: {0}".format(e), 1)
