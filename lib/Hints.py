# Calculates position hints for txs which change an Orchestrator's stake (reward, transferBond)
# The transcoder pool is a linked list sorted by stake. Without hints the contract searches the list from the top for the
# new position, which costs gas for every Orchestrator it passes. With correct hints it can insert directly
# Ported from Cloud SPE's protocol-daemon (internal/providers/bondingmanager/hints.go), which mirrors go-livepeer
import requests #< Fetch the seed list of Orchestrators
# Import our own libraries
from lib import Util, State


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
# How many Orchestrators around a new position get their stake re-read on-chain before trusting a seeded list
CORRECTION_WINDOW = 3
API_TIMEOUT_SECONDS = 5

# Sorted list of [address, stake] for the current round, see getPool
pool_cache = {'round': None, 'pool': None, 'max_size': None, 'source': None}
# Round in which the API last failed, so we only try it once per round
api_failed_round = None


"""
@brief Fetches the active Orchestrators sorted by stake from the Cloud SPE API
@param current_round: the current round number, used to reject stale data
@return list of [address, stake in wei] sorted by stake (descending). Raises an exception if the data is unusable
"""
def fetchPoolFromApi(current_round):
    response = requests.get(State.HINT_API_URL, params={'active_only': 'true', 'limit': 100}, timeout=API_TIMEOUT_SECONDS)
    response.raise_for_status()
    orchestrators = response.json()['data']
    if len(orchestrators) == 0:
        raise Exception("empty list of Orchestrators")
    pool = []
    for orch in orchestrators:
        if int(orch['as_of_round']) < current_round - 1:
            raise Exception("data is from round {0}, while the current round is {1}".format(orch['as_of_round'], current_round))
        # Stake is a decimal string in LPT with 18 decimals
        whole, _, fraction = orch['total_stake'].partition('.')
        stake = int(whole) * 10**18 + int((fraction + '0' * 18)[:18])
        pool.append([orch['address'].lower(), stake])
    for i in range(1, len(pool)):
        if pool[i][1] > pool[i - 1][1]:
            raise Exception("list of Orchestrators is not sorted by stake")
    return pool

"""
@brief Walks the transcoder pool on-chain
@param chain: chain accessor, see Contract.PoolChain
@param max_size: maximum size of the transcoder pool
@return list of [address, stake in wei] sorted by stake (descending). Raises an exception on RPC errors
"""
def fetchPoolOnchain(chain, max_size):
    pool = []
    seen = set()
    current = chain.first().lower()
    while current != ZERO_ADDRESS:
        # Guard against a malformed list
        if current in seen or len(pool) > max_size:
            raise Exception("transcoder pool walk did not end properly at {0}".format(current))
        seen.add(current)
        pool.append([current, chain.stake(current)])
        current = chain.next(current).lower()
    return pool

"""
@brief Returns the cached transcoder pool for the current round, fetching it if required
@param chain: chain accessor, see Contract.PoolChain
@param current_round: the current round number
@return (pool, max_size). Raises an exception if neither the API nor an on-chain walk works
"""
def getPool(chain, current_round):
    global api_failed_round
    if pool_cache['round'] == current_round:
        return pool_cache['pool'], pool_cache['max_size']
    max_size = chain.max_size()
    pool = None
    source = 'onchain'
    if State.HINT_SOURCE == 'cloudspe' and api_failed_round != current_round:
        try:
            pool = fetchPoolFromApi(current_round)
            source = 'cloudspe'
            Util.log("Fetched {0} Orchestrators from the Cloud SPE API for calculating hints".format(len(pool)), 2)
        except Exception as e:
            api_failed_round = current_round
            Util.log("Unable to use the Cloud SPE API for hints, walking the transcoder pool on-chain this round: {0}".format(e), 1)
    if pool is None:
        pool = fetchPoolOnchain(chain, max_size)
        Util.log("Walked the transcoder pool on-chain: {0} Orchestrators".format(len(pool)), 2)
    pool_cache.update({'round': current_round, 'pool': pool, 'max_size': max_size, 'source': source})
    return pool, max_size

"""
@brief Re-reads the stake of the moved Orchestrators and their future neighbours on-chain, so a seeded or cached list is accurate
       where it matters
@param chain: chain accessor, see Contract.PoolChain
@param pool: list of [address, stake], updated in place and re-sorted
@param moves: list of (address, stake change in wei)
"""
def correctPool(chain, pool, moves):
    moved = set(address for address, _ in moves)
    stakes = dict((address, stake) for address, stake in pool)
    # First the moved Orchestrators themselves, since their current stake determines the target positions
    for address in moved:
        if address in stakes:
            stakes[address] = chain.stake(address)
    # Then the Orchestrators around each target position
    others = sorted((item for item in stakes.items() if item[0] not in moved), key=lambda item: item[1], reverse=True)
    window = set()
    target = dict(stakes)
    for address, change in moves:
        if address not in target:
            continue
        target[address] += change
        index = 0
        while index < len(others) and others[index][1] >= target[address]:
            index += 1
        for neighbour, _ in others[max(0, index - CORRECTION_WINDOW):index + CORRECTION_WINDOW]:
            window.add(neighbour)
    for address in window:
        stakes[address] = chain.stake(address)
    pool[:] = sorted(([address, stake] for address, stake in stakes.items()), key=lambda item: item[1], reverse=True)

"""
@brief Simulates moving an Orchestrator to a new stake and returns its new neighbours
@param pool: list of [address, stake] sorted by stake (descending). Updated in place to reflect the move
@param address: the Orchestrator to move
@param new_stake: the stake of the Orchestrator after the move
@return (previous, next) addresses, ZERO_ADDRESS if there is no neighbour. Both ZERO_ADDRESS if the Orchestrator is not in the pool
@note Only members of the pool are moved. The contract only uses the hints of an Orchestrator which is not in the pool when it
      tries to join the pool, which none of our txs do
"""
def simulateMove(pool, address, new_stake):
    index = next((i for i, item in enumerate(pool) if item[0] == address), None)
    if index is None:
        return ZERO_ADDRESS, ZERO_ADDRESS
    pool.pop(index)
    # Insert after any Orchestrators with an equal stake: either side is a valid position for the contract
    index = 0
    while index < len(pool) and pool[index][1] >= new_stake:
        index += 1
    pool.insert(index, [address, new_stake])
    previous = pool[index - 1][0] if index > 0 else ZERO_ADDRESS
    following = pool[index + 1][0] if index < len(pool) - 1 else ZERO_ADDRESS
    return previous, following

"""
@brief Checks hints against the live linked list: the hinted neighbours must be next to each other
@param chain: chain accessor, see Contract.PoolChain
@param steps: list of (address, previous, next) as returned by simulateMove
@param moved: set of addresses being moved, which get skipped as they are not in their final position yet
"""
def verifyHints(chain, steps, moved):
    for address, previous, following in steps:
        if previous == ZERO_ADDRESS and following == ZERO_ADDRESS:
            continue
        current = (chain.first() if previous == ZERO_ADDRESS else chain.next(previous)).lower()
        hops = 0
        while current in moved and hops < len(moved):
            current = chain.next(current).lower()
            hops += 1
        if current != following:
            return False
    return True

"""
@brief Calculates hints for a sequence of stake changes, as done by a single tx
@param chain: chain accessor, see Contract.PoolChain
@param moves: list of (address, stake change in wei), in the order the contract applies them
@return list of (previous, next) per move, or None to send the tx without hints
"""
def calculateHints(chain, moves):
    if State.HINT_SOURCE == 'off':
        return None
    moves = [(address.lower(), change) for address, change in moves]
    moved = set(address for address, _ in moves)
    try:
        current_round = chain.current_round()
        cached_pool, max_size = getPool(chain, current_round)
        for attempt in range(2):
            pool = [list(item) for item in cached_pool]
            correctPool(chain, pool, moves)
            # Store the corrected stakes so the next tx this round starts from better data
            pool_cache['pool'] = [list(item) for item in pool]
            steps = []
            for address, change in moves:
                current = next((item[1] for item in pool if item[0] == address), None)
                if current is None:
                    steps.append((address, ZERO_ADDRESS, ZERO_ADDRESS))
                    continue
                previous, following = simulateMove(pool, address, current + change)
                steps.append((address, previous, following))
            if verifyHints(chain, steps, moved):
                Util.log("Calculated hints: {0}".format(", ".join("{0} between {1} and {2}".format(*step) for step in steps)), 3)
                return [(previous, following) for _, previous, following in steps]
            if attempt == 0:
                # The seeded list misses a change in the pool (an Orchestrator joined or left), so get the real list
                Util.log("Hints did not match the transcoder pool on-chain, walking the transcoder pool on-chain", 2)
                cached_pool = fetchPoolOnchain(chain, max_size)
                pool_cache.update({'round': current_round, 'pool': cached_pool, 'source': 'onchain'})
        Util.log("Hints still do not match the transcoder pool on-chain, sending tx without hints", 1)
    except Exception as e:
        Util.log("Unable to calculate hints, sending tx without hints: {0}".format(e), 1)
    return None
