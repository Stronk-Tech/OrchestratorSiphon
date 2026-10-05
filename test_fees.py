#!/usr/bin/env python3
"""Fee regression: explicit zero tip with a live-base-derived cap.

Under Arbitrum PGA ordering priority tips are collected, so the former
hardcoded 1 gwei tip was charged on every transaction while a zero tip
is still included via the protocol ordering boost. gasParams()
reads the latest block base fee on every call, so retries recompute
instead of reusing stale fees.

No signing, no broadcasts, no network: chain answers are canned
locally, including an adversarial 1 gwei eth_maxPriorityFeePerGas that
must never leak into built transactions. Synthetic addresses only.
"""
import pathlib
import unittest
from unittest import mock

import web3 as web3_pkg
from web3 import Web3
from web3.providers.base import BaseProvider

ROOT = pathlib.Path(__file__).parent

SYNTHETIC_FROM = Web3.to_checksum_address("0x" + "11" * 20)
LIVE_BASE_FEE = 20_000_000
HIST_BASE_FEE = 20_016_000


class CannedArbitrum(BaseProvider):
    def __init__(self, base_fees, priority_hint=1_000_000_000):
        super().__init__()
        self.base_fees = list(base_fees)
        self.calls = []
        self.priority_hint = priority_hint

    def is_connected(self, show_traceback=False):
        return True

    def make_request(self, method, params):
        self.calls.append(method)
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": "0xa4b1"}
        if method == "eth_getBlockByNumber":
            base = (self.base_fees.pop(0) if len(self.base_fees) > 1
                    else self.base_fees[0])
            return {"jsonrpc": "2.0", "id": 1, "result": {
                "number": "0x1e811996",
                "baseFeePerGas": hex(base),
                "gasLimit": "0x4000000000000",
                "timestamp": "0x6901c000",
                "hash": "0x" + "ab" * 32,
                "parentHash": "0x" + "cd" * 32,
            }}
        if method == "eth_estimateGas":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(700_000)}
        if method == "eth_getTransactionCount":
            return {"jsonrpc": "2.0", "id": 1, "result": "0x42"}
        if method == "eth_gasPrice":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(25_000_000)}
        if method == "eth_maxPriorityFeePerGas":
            return {"jsonrpc": "2.0", "id": 1,
                    "result": hex(self.priority_hint)}
        raise AssertionError("unexpected RPC call: %r" % (method,))


def load_contract_module():
    with mock.patch.object(web3_pkg.Web3, "is_connected",
                           return_value=True):
        import importlib
        import lib.Contract as contract
        importlib.reload(contract)
    return contract


class FeeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_module()
        import json
        abi = json.loads(
            (ROOT / "contracts" / "BondingManager.json").read_text())["abi"]
        cls.abi = abi
        cls.bonding = cls.contract.BONDING_CONTRACT_ADDR

    def canned(self, bases):
        provider = CannedArbitrum(bases)
        self.contract.w3 = Web3(provider)
        return provider

    def test_zero_tip_is_explicit_int_not_falsy_fallback(self):
        self.canned([LIVE_BASE_FEE])
        fees = self.contract.gasParams()
        self.assertIn("maxPriorityFeePerGas", fees)
        self.assertIs(type(fees["maxPriorityFeePerGas"]), int)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def test_cap_is_twice_live_base_exact_int(self):
        for base in (LIVE_BASE_FEE, HIST_BASE_FEE, 1):
            self.canned([base])
            fees = self.contract.gasParams()
            self.assertIs(type(fees["maxFeePerGas"]), int)
            self.assertEqual(fees["maxFeePerGas"], 2 * base)

    def test_fees_refresh_between_retries(self):
        self.canned([HIST_BASE_FEE, LIVE_BASE_FEE + 3])
        first = self.contract.gasParams()
        second = self.contract.gasParams()
        self.assertEqual(first["maxFeePerGas"], 2 * HIST_BASE_FEE)
        self.assertEqual(second["maxFeePerGas"], 2 * (LIVE_BASE_FEE + 3))
        self.assertNotEqual(first["maxFeePerGas"], second["maxFeePerGas"])
        self.assertEqual(second["maxPriorityFeePerGas"], 0)

    def test_big_int_base_fee_exactness(self):
        # Lift the fee cap so the exact multiplication is visible
        self.contract.GAS_CAP_WEI = 2 ** 64
        self.addCleanup(setattr, self.contract, "GAS_CAP_WEI", 1000000000)
        for base in (2 ** 53 + 1, 2 ** 60 + 7):
            self.canned([base])
            fees = self.contract.gasParams()
            self.assertEqual(fees["maxFeePerGas"], 2 * base)
            self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def test_reward_build_uses_helper_fees_no_legacy_fields(self):
        provider = self.canned([LIVE_BASE_FEE])
        w3 = Web3(provider)
        bonding = w3.eth.contract(address=self.bonding, abi=self.abi)
        fees = self.contract.gasParams()
        calls_before = list(provider.calls)
        tx = bonding.functions.reward().build_transaction({
            "from": SYNTHETIC_FROM,
            "nonce": 66,
            **fees,
        })
        self.assertEqual(tx["maxPriorityFeePerGas"], 0)
        self.assertIs(type(tx["maxPriorityFeePerGas"]), int)
        self.assertEqual(int(tx["maxFeePerGas"]), 2 * LIVE_BASE_FEE)
        self.assertNotIn("gasPrice", tx)
        for method in provider.calls[len(calls_before):]:
            self.assertFalse(method.startswith("eth_send"), method)
            self.assertNotIn(method, ("eth_sign", "eth_signTransaction"))

    def test_no_hardcoded_fees_remain_at_tx_sites(self):
        text = (ROOT / "lib" / "Contract.py").read_text()
        self.assertNotIn("'maxFeePerGas': 2000000000", text)
        self.assertNotIn("'maxPriorityFeePerGas': 1000000000", text)
        self.assertEqual(text.count("**gasParams()"), 8)


if __name__ == "__main__":
    unittest.main()
