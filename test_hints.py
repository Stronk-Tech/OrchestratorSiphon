#!/usr/bin/env python3
"""
Offline tests for lib/Hints.py: hint calculation, correcting a seeded list on-chain and all fallbacks.

No network: the transcoder pool is a local linked list, the Cloud SPE API is mocked.
Hints are checked the way the contract (SortedDoublyLL.validInsertPosition) checks them.
Run with: python3 -m unittest test_hints
"""
import unittest
from unittest import mock

from lib import Hints, State

ZERO = Hints.ZERO_ADDRESS
LPT = 10**18


def addr(n):
    # Offset so no fake Orchestrator is the zero address
    return "0x" + format(0x1000 + n, "040x")


class FakeChain:
    """Transcoder pool as a sorted linked list, with call counters"""

    def __init__(self, stakes, round_num=4360, max_size=100):
        self.stakes = dict(stakes)
        self.round_num = round_num
        self.size = max_size
        self.calls = {'first': 0, 'next': 0, 'stake': 0}
        self.fail = False

    def order(self):
        return [a for a, _ in sorted(self.stakes.items(), key=lambda item: item[1], reverse=True)]

    def current_round(self):
        return self.round_num

    def max_size(self):
        return self.size

    def first(self):
        self.check()
        self.calls['first'] += 1
        order = self.order()
        return order[0] if order else ZERO

    def next(self, address):
        self.check()
        self.calls['next'] += 1
        order = self.order()
        index = order.index(address)
        return order[index + 1] if index + 1 < len(order) else ZERO

    def stake(self, address):
        self.check()
        self.calls['stake'] += 1
        return self.stakes.get(address, 0)

    def check(self):
        if self.fail:
            raise Exception("RPC down")

    def apply(self, address, new_stake, previous, following):
        """Applies a move like SortedDoublyLL.updateKey and returns whether the hints were an exact valid insert position"""
        stakes = dict(self.stakes)
        del stakes[address]
        order = [a for a, _ in sorted(stakes.items(), key=lambda item: item[1], reverse=True)]
        if previous == ZERO and following == ZERO:
            valid = len(order) == 0
        elif previous == ZERO:
            valid = order[0] == following and new_stake >= stakes[following]
        elif following == ZERO:
            valid = order[-1] == previous and new_stake <= stakes[previous]
        else:
            index = order.index(previous) if previous in order else -2
            valid = (index + 1 < len(order) and order[index + 1] == following
                     and stakes[previous] >= new_stake >= stakes[following])
        self.stakes[address] = new_stake
        return valid


def api_response(pool, as_of_round=4360):
    data = [{'address': a, 'total_stake': "{0}.{1:018d}".format(s // LPT, s % LPT), 'as_of_round': str(as_of_round)}
            for a, s in pool]
    response = mock.Mock()
    response.raise_for_status = mock.Mock()
    response.json = mock.Mock(return_value={'data': data, 'meta': {}})
    return response


class HintTests(unittest.TestCase):
    def setUp(self):
        Hints.pool_cache.update({'round': None, 'pool': None, 'max_size': None, 'source': None})
        Hints.api_failed_round = None
        self.orig_source = State.HINT_SOURCE
        State.HINT_SOURCE = 'onchain'
        # 20 Orchestrators with stakes 2000, 1900, ... 100 LPT
        self.chain = FakeChain({addr(i): (20 - i) * 100 * LPT for i in range(20)})

    def tearDown(self):
        State.HINT_SOURCE = self.orig_source

    def assertExact(self, chain, moves, hints):
        self.assertIsNotNone(hints)
        for (address, change), (previous, following) in zip(moves, hints):
            new_stake = chain.stakes[address] + change
            self.assertTrue(chain.apply(address, new_stake, previous, following),
                            "hints {0}/{1} not exact for {2} -> {3}".format(previous, following, address, new_stake))

    def test_simulate_move_middle_head_tail(self):
        pool = [[addr(i), (20 - i) * LPT] for i in range(5)]
        self.assertEqual(Hints.simulateMove([list(x) for x in pool], addr(2), 17 * LPT + LPT // 2), (addr(1), addr(3)))
        self.assertEqual(Hints.simulateMove([list(x) for x in pool], addr(3), 50 * LPT), (ZERO, addr(0)))
        self.assertEqual(Hints.simulateMove([list(x) for x in pool], addr(1), 1 * LPT), (addr(4), ZERO))
        self.assertEqual(Hints.simulateMove([list(x) for x in pool], addr(99), 1 * LPT), (ZERO, ZERO))

    def test_reward_hints_onchain(self):
        moves = [(addr(15), 1250 * LPT)]
        self.assertExact(self.chain, moves, Hints.calculateHints(self.chain, moves))

    def test_transfer_bond_back_to_same_orch(self):
        # Receiver delegated to the Orch itself: drops, then comes back to the original stake
        moves = [(addr(5), -800 * LPT), (addr(5), 800 * LPT)]
        self.assertExact(self.chain, moves, Hints.calculateHints(self.chain, moves))

    def test_transfer_bond_to_other_delegate(self):
        moves = [(addr(2), -1000 * LPT), (addr(12), 1000 * LPT)]
        self.assertExact(self.chain, moves, Hints.calculateHints(self.chain, moves))

    def test_cloudspe_stale_stakes_get_corrected(self):
        State.HINT_SOURCE = 'cloudspe'
        seed = [(a, s) for a, s in sorted(self.chain.stakes.items(), key=lambda item: item[1], reverse=True)]
        # Since the snapshot, the Orchestrators around the target position have changed places on-chain
        self.chain.stakes[addr(6)] = 1450 * LPT
        self.chain.stakes[addr(7)] = 1460 * LPT
        moves = [(addr(15), 1000 * LPT)]
        with mock.patch.object(Hints.requests, 'get', return_value=api_response(seed)) as get:
            hints = Hints.calculateHints(self.chain, moves)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(self.chain.calls['first'] + self.chain.calls['next'], 1, "should not walk the whole pool")
        self.assertExact(self.chain, moves, hints)

    def test_cloudspe_missing_orch_falls_back_to_walk(self):
        State.HINT_SOURCE = 'cloudspe'
        seed = [(a, s) for a, s in sorted(self.chain.stakes.items(), key=lambda item: item[1], reverse=True)]
        # An Orchestrator joined the pool right at the target position (500 + 1000 LPT) after the snapshot
        self.chain.stakes[addr(50)] = 1450 * LPT
        moves = [(addr(15), 1000 * LPT)]
        with mock.patch.object(Hints.requests, 'get', return_value=api_response(seed)):
            hints = Hints.calculateHints(self.chain, moves)
        self.assertEqual(Hints.pool_cache['source'], 'onchain')
        self.assertExact(self.chain, moves, hints)

    def test_cloudspe_join_elsewhere_needs_no_walk(self):
        State.HINT_SOURCE = 'cloudspe'
        seed = [(a, s) for a, s in sorted(self.chain.stakes.items(), key=lambda item: item[1], reverse=True)]
        # An Orchestrator joined far away from the target position: the seeded hints are still exact
        self.chain.stakes[addr(50)] = 105 * LPT
        moves = [(addr(15), 1000 * LPT)]
        with mock.patch.object(Hints.requests, 'get', return_value=api_response(seed)):
            hints = Hints.calculateHints(self.chain, moves)
        self.assertEqual(Hints.pool_cache['source'], 'cloudspe')
        self.assertExact(self.chain, moves, hints)

    def test_api_down_walks_once_per_round(self):
        State.HINT_SOURCE = 'cloudspe'
        with mock.patch.object(Hints.requests, 'get', side_effect=Exception("connection refused")) as get:
            first = [(addr(15), 1000 * LPT)]
            self.assertExact(self.chain, first, Hints.calculateHints(self.chain, first))
            walks = self.chain.calls['first']
            second = [(addr(10), 50 * LPT)]
            self.assertExact(self.chain, second, Hints.calculateHints(self.chain, second))
        self.assertEqual(get.call_count, 1, "API should only be tried once per round")
        self.assertEqual(Hints.pool_cache['source'], 'onchain')
        # The second calculation reuses the cached walk: no new walk from the head of the list
        self.assertLessEqual(self.chain.calls['first'] - walks, 1)

    def test_api_retried_next_round(self):
        State.HINT_SOURCE = 'cloudspe'
        with mock.patch.object(Hints.requests, 'get', side_effect=Exception("down")) as get:
            Hints.calculateHints(self.chain, [(addr(15), LPT)])
            self.chain.round_num += 1
            Hints.calculateHints(self.chain, [(addr(15), LPT)])
        self.assertEqual(get.call_count, 2)

    def test_api_stale_round_rejected(self):
        State.HINT_SOURCE = 'cloudspe'
        seed = list(self.chain.stakes.items())
        with mock.patch.object(Hints.requests, 'get', return_value=api_response(seed, as_of_round=4300)):
            moves = [(addr(15), 1000 * LPT)]
            self.assertExact(self.chain, moves, Hints.calculateHints(self.chain, moves))
        self.assertEqual(Hints.pool_cache['source'], 'onchain')

    def test_api_unsorted_rejected(self):
        seed = list(reversed(sorted(self.chain.stakes.items(), key=lambda item: item[1], reverse=True)))
        with mock.patch.object(Hints.requests, 'get', return_value=api_response(seed)):
            with self.assertRaises(Exception):
                Hints.fetchPoolFromApi(4360)

    def test_api_stake_parsing_is_exact(self):
        with mock.patch.object(Hints.requests, 'get', return_value=api_response([(addr(1), 4360437561831037829448279)])):
            self.assertEqual(Hints.fetchPoolFromApi(4360), [[addr(1), 4360437561831037829448279]])

    def test_chain_failure_sends_without_hints(self):
        self.chain.fail = True
        self.assertIsNone(Hints.calculateHints(self.chain, [(addr(15), LPT)]))

    def test_source_off(self):
        State.HINT_SOURCE = 'off'
        self.assertIsNone(Hints.calculateHints(self.chain, [(addr(15), LPT)]))
        self.assertEqual(sum(self.chain.calls.values()), 0)

    def test_orch_not_in_pool_gets_zero_hints(self):
        hints = Hints.calculateHints(self.chain, [(addr(99), LPT)])
        self.assertEqual(hints, [(ZERO, ZERO)])


if __name__ == "__main__":
    unittest.main()
