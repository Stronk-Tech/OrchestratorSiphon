#!/usr/bin/env python3
"""
Offline tests for gasParams(): zero priority tip, maxFeePerGas derived from the live base fee,
the configured cap and the fallback when the base fee can't be read.

No signing, no broadcasts, no network: chain answers are canned locally, including a 1 gwei
eth_maxPriorityFeePerGas suggestion that must never leak into built transactions.
Run with: python3 -m unittest test_fees
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
    def __init__(self, base_fees, priority_hint=1_000_000_000, fail_blocks=False, receipt_status=1):
        super().__init__()
        self.receipt_status = receipt_status
        self.sent = []
        self.base_fees = list(base_fees)
        self.calls = []
        self.priority_hint = priority_hint
        self.fail_blocks = fail_blocks

    def is_connected(self, show_traceback=False):
        return True

    def make_request(self, method, params):
        self.calls.append(method)
        if method == "eth_chainId":
            return {"jsonrpc": "2.0", "id": 1, "result": "0xa4b1"}
        if method == "eth_getBlockByNumber":
            if self.fail_blocks:
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "rate limited"}}
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
        if method == "eth_sendRawTransaction":
            self.sent.append(params[0])
            return {"jsonrpc": "2.0", "id": 1, "result": "0x" + "ee" * 32}
        if method == "eth_getTransactionReceipt":
            return {"jsonrpc": "2.0", "id": 1, "result": {
                "transactionHash": "0x" + "ee" * 32,
                "blockNumber": "0x1e811997",
                "blockHash": "0x" + "ab" * 32,
                "status": hex(self.receipt_status),
                "gasUsed": hex(600_000),
                "cumulativeGasUsed": hex(600_000),
                "effectiveGasPrice": hex(LIVE_BASE_FEE),
                "logs": [],
                "logsBloom": "0x" + "00" * 256,
                "transactionIndex": "0x1",
                "from": SYNTHETIC_FROM,
                "to": SYNTHETIC_FROM,
                "contractAddress": None,
                "type": "0x2",
            }}
        raise AssertionError("unexpected RPC call: %r" % (method,))


def load_contract_module():
    with mock.patch.object(web3_pkg.Web3, "is_connected",
                           return_value=True):
        import importlib
        import lib.Contract as contract
        importlib.reload(contract)
    return contract


class GasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract_module()
        cls.orig_w3 = cls.contract.w3
        cls.orig_cap = cls.contract.GAS_CAP_WEI
        cls.orig_headroom = cls.contract.GAS_HEADROOM_PERMILLE

    def setUp(self):
        # Pin the defaults so the tests don't depend on the local config.ini
        self.contract.GAS_CAP_WEI = 2_000_000_000
        self.contract.GAS_HEADROOM_PERMILLE = 2000

    @classmethod
    def tearDownClass(cls):
        cls.contract.w3 = cls.orig_w3
        cls.contract.GAS_CAP_WEI = cls.orig_cap
        cls.contract.GAS_HEADROOM_PERMILLE = cls.orig_headroom

    def canned(self, bases, **kwargs):
        provider = CannedArbitrum(bases, **kwargs)
        self.contract.w3 = Web3(provider)
        return provider

    def test_zero_tip_is_explicit_int(self):
        self.canned([LIVE_BASE_FEE])
        fees = self.contract.gasParams()
        self.assertIn("maxPriorityFeePerGas", fees)
        self.assertIs(type(fees["maxPriorityFeePerGas"]), int)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def test_max_fee_is_headroom_times_live_base(self):
        for base in (LIVE_BASE_FEE, HIST_BASE_FEE, 1):
            self.canned([base])
            fees = self.contract.gasParams()
            self.assertIs(type(fees["maxFeePerGas"]), int)
            self.assertEqual(fees["maxFeePerGas"], 2 * base)

    def test_fractional_headroom_is_exact_int(self):
        self.contract.GAS_HEADROOM_PERMILLE = 1500
        self.canned([LIVE_BASE_FEE + 1])
        fees = self.contract.gasParams()
        self.assertEqual(fees["maxFeePerGas"], (LIVE_BASE_FEE + 1) * 3 // 2)

    def test_max_fee_is_capped(self):
        # Base fee spike: 2x base would exceed the cap, so the cap wins
        self.canned([1_500_000_000])
        self.assertEqual(self.contract.gasParams()["maxFeePerGas"], 2_000_000_000)
        # Base fee above the cap: still never more than the cap
        self.canned([5_000_000_000])
        fees = self.contract.gasParams()
        self.assertEqual(fees["maxFeePerGas"], 2_000_000_000)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def test_fallback_when_base_fee_unreadable(self):
        self.canned([LIVE_BASE_FEE], fail_blocks=True)
        fees = self.contract.gasParams()
        self.assertEqual(fees["maxFeePerGas"], self.contract.GAS_FALLBACK_WEI)
        self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def test_fees_refresh_between_calls(self):
        self.canned([HIST_BASE_FEE, LIVE_BASE_FEE + 3])
        first = self.contract.gasParams()
        second = self.contract.gasParams()
        self.assertEqual(first["maxFeePerGas"], 2 * HIST_BASE_FEE)
        self.assertEqual(second["maxFeePerGas"], 2 * (LIVE_BASE_FEE + 3))
        self.assertEqual(second["maxPriorityFeePerGas"], 0)

    def test_big_int_base_fee_exactness(self):
        self.contract.GAS_CAP_WEI = 2 ** 64
        for base in (2 ** 53 + 1, 2 ** 60 + 7):
            self.canned([base])
            fees = self.contract.gasParams()
            self.assertEqual(fees["maxFeePerGas"], 2 * base)
            self.assertEqual(fees["maxPriorityFeePerGas"], 0)

    def test_reward_build_uses_gas_params_no_legacy_fields(self):
        provider = self.canned([LIVE_BASE_FEE])
        bonding = self.contract.w3.eth.contract(
            address=self.contract.BONDING_CONTRACT_ADDR,
            abi=self.contract.abi_bonding_manager)
        tx = bonding.functions.reward().build_transaction({
            "from": SYNTHETIC_FROM,
            "nonce": 66,
            **self.contract.gasParams(),
        })
        self.assertEqual(tx["maxPriorityFeePerGas"], 0)
        self.assertEqual(int(tx["maxFeePerGas"]), 2 * LIVE_BASE_FEE)
        self.assertNotIn("gasPrice", tx)
        self.assertNotIn("eth_maxPriorityFeePerGas", provider.calls)
        for method in provider.calls:
            self.assertFalse(method.startswith("eth_send"), method)
            self.assertNotIn(method, ("eth_sign", "eth_signTransaction"))

    def test_no_hardcoded_fees_at_tx_sites(self):
        text = (ROOT / "lib" / "Contract.py").read_text()
        self.assertNotIn("'maxFeePerGas': 2000000000", text)
        self.assertNotIn("'maxPriorityFeePerGas': 1000000000", text)
        self.assertEqual(text.count("maxPriorityFeePerGas"), 1)



class SendTxTests(unittest.TestCase):
    """sendTx() against the canned chain: signs locally with a throwaway key, 'broadcasts' to the stub only"""

    @classmethod
    def setUpClass(cls):
        from eth_account import Account
        cls.contract = load_contract_module()
        cls.orig_w3 = cls.contract.w3
        account = Account.from_key("0x" + "22" * 32)

        class FakeOrch:
            source_checksum_address = account.address
            source_private_key = account.key
        cls.orch = FakeOrch()

    @classmethod
    def tearDownClass(cls):
        cls.contract.w3 = cls.orig_w3

    def setUp(self):
        self.orig_orchs = list(self.contract.State.orchestrators)
        self.contract.State.orchestrators[:] = [self.orch]

    def tearDown(self):
        self.contract.State.orchestrators[:] = self.orig_orchs

    def canned(self, **kwargs):
        provider = CannedArbitrum([LIVE_BASE_FEE], **kwargs)
        self.contract.w3 = Web3(provider)
        return provider

    def bonding(self):
        return self.contract.w3.eth.contract(
            address=self.contract.BONDING_CONTRACT_ADDR,
            abi=self.contract.abi_bonding_manager)

    def test_contract_call_is_sent_with_zero_tip(self):
        provider = self.canned()
        receipt = self.contract.sendTx(0, self.bonding().functions.reward())
        self.assertEqual(receipt["status"], 1)
        self.assertEqual(len(provider.sent), 1)
        from eth_account.typed_transactions import TypedTransaction
        from hexbytes import HexBytes
        tx = TypedTransaction.from_bytes(HexBytes(provider.sent[0])).as_dict()
        self.assertEqual(tx["maxPriorityFeePerGas"], 0)
        self.assertEqual(tx["maxFeePerGas"], 2 * LIVE_BASE_FEE)

    def test_plain_transaction_dict_is_sent(self):
        provider = self.canned()
        self.contract.sendTx(0, {"to": SYNTHETIC_FROM, "value": 1, "gas": 21000, "chainId": 42161})
        self.assertEqual(len(provider.sent), 1)

    def test_reverted_receipt_raises(self):
        self.canned(receipt_status=0)
        with self.assertRaises(Exception) as ctx:
            self.contract.sendTx(0, self.bonding().functions.reward())
        self.assertIn("reverted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
