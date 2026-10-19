"""
Unit tests for PurchaseGuard Intelligent Contract.
Mocks the GenLayer runtime environment (gl, TreeMap, u256, Address, gl.nondet.web.get)
to verify all contract state transitions, independent vendor evidence acquisition,
verbatim quote validation, and deterministic safety clamps.
"""

import sys
import os
import json
import unittest

# --- Mock GenLayer Runtime for Local Unit Testing ---
class Address(str):
    def __repr__(self):
        return f"Address('{self}')"


class u256(int):
    def __new__(cls, val):
        return super().__new__(cls, val)


class TreeMap(dict):
    pass


class DynArray(list):
    pass


class MockMessage:
    def __init__(self):
        self.sender_address = Address("0xBuyer11111111111111111111111111111111111")
        self.origin_address = Address("0xBuyer11111111111111111111111111111111111")


class MockBlock:
    def __init__(self):
        self.timestamp = 1791400000


class MockWebResponse:
    def __init__(self, text: str):
        self.body = text.encode("utf-8")

    def __str__(self):
        return self.body.decode("utf-8")


class MockNondetWeb:
    def __init__(self):
        self.responses = {}

    def get(self, url: str):
        if url in self.responses:
            return MockWebResponse(self.responses[url])
        # Default mock response
        return MockWebResponse(json.dumps({
            "title": "Default Item",
            "price_cents": 8999,
            "condition": "NEW",
            "stock_status": "IN_STOCK"
        }))


class MockNondet:
    def __init__(self):
        self.web = MockNondetWeb()


class MockEqPrinciple:
    def __init__(self):
        self.mock_response = None

    def prompt_non_comparative(self, get_input_fn, task="", criteria=""):
        if self.mock_response is not None:
            return self.mock_response

        user_input = get_input_fn()
        if "Generic Low-End SATA" in user_input or "BUDGET-SATA" in user_input:
            return json.dumps({
                "decision": "REJECTED",
                "vendor_price_cents": 4500,
                "stock_status": "IN_STOCK",
                "condition": "REFURBISHED",
                "verbatim_quote": "\"condition\": \"REFURBISHED\"",
                "rationale": "Product is refurbished and downgraded to SATA speeds, violating NEW_ONLY and NVMe specs."
            })
        elif "14999" in user_input:
            return json.dumps({
                "decision": "REJECTED",
                "vendor_price_cents": 14999,
                "stock_status": "IN_STOCK",
                "condition": "NEW",
                "verbatim_quote": "\"price_cents\": 14999",
                "rationale": "Actual vendor price of $149.99 exceeds buyer max budget ceiling."
            })
        elif "Crucial P5 Plus" in user_input:
            return json.dumps({
                "decision": "APPROVED",
                "vendor_price_cents": 8999,
                "stock_status": "IN_STOCK",
                "condition": "NEW",
                "verbatim_quote": "\"product_title\": \"Crucial P5 Plus 1TB PCIe 4.0 3D NAND NVMe M.2 Gaming SSD\"",
                "rationale": "Meets all NVMe speed, capacity, and brand requirements within budget."
            })
        else:
            return json.dumps({
                "decision": "APPROVED",
                "vendor_price_cents": 8500,
                "stock_status": "IN_STOCK",
                "condition": "NEW",
                "verbatim_quote": "\"condition\": \"NEW\"",
                "rationale": "Acceptable functional equivalent."
            })


class MockContract:
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        obj.mandates = TreeMap()
        obj.proposals = TreeMap()
        obj.adjudications = TreeMap()
        obj.mandate_counter = u256(0)
        return obj


class MockPublic:
    @staticmethod
    def view(f):
        return f

    @staticmethod
    def write(f):
        return f


class MockGLModule:
    def __init__(self):
        self.Contract = MockContract
        self.message = MockMessage()
        self.block = MockBlock()
        self.nondet = MockNondet()
        self.eq_principle = MockEqPrinciple()
        self.public = MockPublic()


# Register mocks in sys.modules
mock_gl = MockGLModule()
genlayer_mock = type(sys)("genlayer")
genlayer_mock.gl = mock_gl
genlayer_mock.Address = Address
genlayer_mock.u256 = u256
genlayer_mock.TreeMap = TreeMap
genlayer_mock.DynArray = DynArray
sys.modules["genlayer"] = genlayer_mock

# Add contracts path to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "contracts")))
from purchase_guard import PurchaseGuard


class TestPurchaseGuard(unittest.TestCase):
    def setUp(self):
        mock_gl.message.sender_address = Address("0xBuyer11111111111111111111111111111111111")
        mock_gl.eq_principle.mock_response = None
        self.guard = PurchaseGuard()
        self.buyer = "0xBuyer11111111111111111111111111111111111"
        self.agent = "0xAgent22222222222222222222222222222222222"
        self.intruder = "0xIntruder9999999999999999999999999999999"

        # Mock vendor URL bodies
        self.url_honest = "https://raw.githubusercontent.com/kosaiyno/genlayer-purchase-guard/main/evidence/honest_crucial_ssd.json"
        self.url_downgraded = "https://raw.githubusercontent.com/kosaiyno/genlayer-purchase-guard/main/evidence/downgraded_sata_ssd.json"
        self.url_surge = "https://raw.githubusercontent.com/kosaiyno/genlayer-purchase-guard/main/evidence/price_surged_ssd.json"

        mock_gl.nondet.web.responses[self.url_honest] = json.dumps({
            "product_title": "Crucial P5 Plus 1TB PCIe 4.0 3D NAND NVMe M.2 Gaming SSD",
            "price_cents": 8999,
            "stock_status": "IN_STOCK",
            "condition": "NEW",
            "specifications": {"capacity": "1TB", "interface": "PCIe 4.0 x4 NVMe"}
        })
        mock_gl.nondet.web.responses[self.url_downgraded] = json.dumps({
            "product_title": "Generic Low-End SATA III 2.5 Inch Internal Solid State Drive",
            "price_cents": 4500,
            "stock_status": "IN_STOCK",
            "condition": "REFURBISHED",
            "specifications": {"capacity": "256GB", "interface": "SATA III"}
        })
        mock_gl.nondet.web.responses[self.url_surge] = json.dumps({
            "product_title": "Samsung 980 PRO 1TB PCIe 4.0 NVMe SSD High Performance",
            "price_cents": 14999,
            "stock_status": "IN_STOCK",
            "condition": "NEW",
            "specifications": {"capacity": "1TB"}
        })

    def test_initialization(self):
        self.assertEqual(int(self.guard.get_total_mandates()), 0)
        stats = self.guard.get_guard_stats()
        self.assertIn("Total Mandates Registered: 0", stats)

    def test_create_mandate_success(self):
        mandate_id = self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0 read >= 7000MB/s",
            brand_rule="PREFERRED",
            condition_rule="NEW_ONLY"
        )
        self.assertEqual(int(mandate_id), 1)
        self.assertEqual(int(self.guard.get_total_mandates()), 1)
        self.assertEqual(self.guard.get_mandate_status(1), "ACTIVE")

    def test_propose_substitution(self):
        self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="PREFERRED",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        res = self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Crucial P5 Plus 1TB NVMe SSD",
            vendor_url=self.url_honest,
            proposed_price_cents=8999,
            agent_notes="Direct partner verified stock"
        )
        self.assertTrue(res)
        self.assertEqual(self.guard.get_mandate_status(1), "PROPOSED")

    def test_adjudicate_honest_approved_and_confirmed(self):
        self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="PREFERRED",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Crucial P5 Plus 1TB NVMe SSD",
            vendor_url=self.url_honest,
            proposed_price_cents=8999,
            agent_notes="Stock replacement"
        )

        res = self.guard.adjudicate_substitution(1)
        parsed = json.loads(res)
        self.assertEqual(parsed["decision"], "APPROVED")
        self.assertEqual(self.guard.get_mandate_status(1), "APPROVED")

        confirm_res = self.guard.confirm_purchase(1)
        self.assertTrue(confirm_res)
        self.assertEqual(self.guard.get_mandate_status(1), "EXECUTED")

    def test_adjudicate_catches_downgraded_and_refurbished_abuse(self):
        self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        # Malicious or buggy agent proposes a cheap SATA refurbished drive claiming it meets specs
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Cheap Drive",
            vendor_url=self.url_downgraded,
            proposed_price_cents=4500,
            agent_notes="Claims it is an NVMe substitute"
        )

        res = self.guard.adjudicate_substitution(1)
        parsed = json.loads(res)
        self.assertEqual(parsed["decision"], "REJECTED")
        self.assertEqual(self.guard.get_mandate_status(1), "REJECTED")
        self.assertIn("REFURBISHED", parsed["condition"])

    def test_adjudicate_catches_price_surge_budget_overrun(self):
        self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,  # $100 max
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        # Agent claims price is 9500 ($95), but actual vendor page has surged price to 14999 ($149.99)
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Surged SSD",
            vendor_url=self.url_surge,
            proposed_price_cents=9500,
            agent_notes="Claiming discount"
        )

        res = self.guard.adjudicate_substitution(1)
        parsed = json.loads(res)
        self.assertEqual(parsed["decision"], "REJECTED")
        self.assertEqual(self.guard.get_mandate_status(1), "REJECTED")
        self.assertIn("Deterministic clamp", parsed["rationale"])

    def test_verbatim_quote_enforcement(self):
        self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Crucial P5 Plus",
            vendor_url=self.url_honest,
            proposed_price_cents=8999,
            agent_notes="Honest specs"
        )

        # Mock LLM returning missing/blank verbatim quote
        mock_gl.eq_principle.mock_response = json.dumps({
            "decision": "APPROVED",
            "vendor_price_cents": 8999,
            "stock_status": "IN_STOCK",
            "condition": "NEW",
            "verbatim_quote": "",  # Missing quote
            "rationale": "Looks good"
        })

        res = self.guard.adjudicate_substitution(1)
        parsed = json.loads(res)
        self.assertEqual(parsed["decision"], "REJECTED")
        self.assertIn("Missing verifiable verbatim quote", parsed["rationale"])

    def test_buyer_override_flow(self):
        self.guard.create_mandate(
            target_item="Flagship SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe",
            brand_rule="PREFERRED",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(1, "Off-Brand SSD", self.url_honest, 8000, "Notes")

        mock_gl.eq_principle.mock_response = json.dumps({
            "decision": "NEEDS_USER_APPROVAL",
            "vendor_price_cents": 8000,
            "stock_status": "IN_STOCK",
            "condition": "NEW",
            "verbatim_quote": "\"price_cents\": 8999",
            "rationale": "Soft brand preference deviation"
        })

        self.guard.adjudicate_substitution(1)
        self.assertEqual(self.guard.get_mandate_status(1), "NEEDS_USER_APPROVAL")

        # Unauthorized caller cannot override
        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(Exception):
            self.guard.buyer_override(1, approve=True)

        # Buyer approves
        mock_gl.message.sender_address = Address(self.buyer)
        self.guard.buyer_override(1, approve=True)
        self.assertEqual(self.guard.get_mandate_status(1), "APPROVED")

    def test_cancellation_access_control(self):
        self.guard.create_mandate(
            target_item="SSD",
            max_budget_cents=10000,
            required_specs="1TB",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(Exception):
            self.guard.cancel_mandate(1)

        mock_gl.message.sender_address = Address(self.buyer)
        self.guard.cancel_mandate(1)
        self.assertEqual(self.guard.get_mandate_status(1), "CANCELLED")


if __name__ == "__main__":
    unittest.main()
