"""
Unit tests for PurchaseGuard Intelligent Contract.
Mocks the GenLayer runtime environment (gl, TreeMap, u256, Address, gl.nondet.web.get)
to verify all contract state transitions, independent vendor evidence acquisition,
verbatim quote validation, deterministic safety clamps, and mandate authorization controls.
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
        self.sender_address = Address("0x1111111111111111111111111111111111111111")
        self.origin_address = Address("0x1111111111111111111111111111111111111111")


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
                "verbatim_quote": "\"price_cents\": 8999",
                "rationale": "Product satisfies PCIe 4.0 NVMe specifications within budget."
            })
        else:
            return json.dumps({
                "decision": "APPROVED",
                "vendor_price_cents": 8999,
                "stock_status": "IN_STOCK",
                "condition": "NEW",
                "verbatim_quote": "\"price_cents\": 8999",
                "rationale": "Satisfies specs."
            })


class MockPublic:
    def view(self, fn):
        return fn

    def write(self, fn):
        return fn


class MockContract:
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        obj.mandates = TreeMap()
        obj.proposals = TreeMap()
        obj.adjudications = TreeMap()
        obj.mandate_counter = u256(0)
        return obj


class MockGLModule:
    def __init__(self):
        self.message = MockMessage()
        self.block = MockBlock()
        self.nondet = MockNondet()
        self.eq_principle = MockEqPrinciple()
        self.public = MockPublic()
        self.Contract = MockContract


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
        self.buyer = "0x1111111111111111111111111111111111111111"
        self.agent = "0x2222222222222222222222222222222222222222"
        self.former_agent = "0x3333333333333333333333333333333333333333"
        self.intruder = "0x9999999999999999999999999999999999999999"

        mock_gl.message.sender_address = Address(self.buyer)
        mock_gl.eq_principle.mock_response = None
        self.guard = PurchaseGuard()

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
            condition_rule="NEW_ONLY",
            authorized_agent=self.agent
        )
        self.assertEqual(int(mandate_id), 1)
        self.assertEqual(int(self.guard.get_total_mandates()), 1)
        self.assertEqual(self.guard.get_mandate_status(1), "ACTIVE")

    # =========================================================================
    # STEWARD & REVIEWER AUTHORIZATION SUITE (ALL 9 CORE CASES)
    # =========================================================================

    def test_case_1_unrelated_account_submits_proposal_rejected(self):
        """Case 1: Unrelated account cannot submit proposal; storage remains unchanged."""
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent=self.agent)
        initial_mandate_json = self.guard.get_mandate(m)

        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(PermissionError) as ctx:
            self.guard.propose_substitution(m, "Rogue Drive", self.url_honest, 8000, "Hijack")

        self.assertIn("Unauthorized proposal submission", str(ctx.exception))
        # Verify storage remains completely unchanged
        self.assertEqual(self.guard.get_mandate_status(m), "ACTIVE")
        self.assertEqual(self.guard.get_mandate(m), initial_mandate_json)
        self.assertIn("Proposal not found", self.guard.get_proposal(m))

    def test_case_2_buyer_submits_proposal_accepted(self):
        """Case 2: Buyer submits proposal directly without requiring an agent."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")
        res = self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Buyer proposal")
        self.assertTrue(res)
        self.assertEqual(self.guard.get_mandate_status(m), "PROPOSED")

    def test_case_3_authorized_agent_submits_proposal_accepted(self):
        """Case 3: Explicitly authorized agent submits proposal."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent=self.agent)

        mock_gl.message.sender_address = Address(self.agent)
        res = self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Agent proposal")
        self.assertTrue(res)
        self.assertEqual(self.guard.get_mandate_status(m), "PROPOSED")

    def test_case_4_unrelated_account_confirms_purchase_rejected(self):
        """Case 4: Unrelated account cannot confirm purchase; status remains APPROVED, not EXECUTED."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent=self.agent)
        self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Notes")
        self.guard.adjudicate_substitution(m)
        self.assertEqual(self.guard.get_mandate_status(m), "APPROVED")

        # Intruder attempts to trigger confirmation
        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(PermissionError) as ctx:
            self.guard.confirm_purchase(m)

        self.assertIn("Unauthorized purchase confirmation", str(ctx.exception))
        # Verify storage remains APPROVED and was NOT transitioned to EXECUTED
        self.assertEqual(self.guard.get_mandate_status(m), "APPROVED")

    def test_case_5_buyer_confirms_purchase_accepted(self):
        """Case 5: Buyer confirms approved purchase directly."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")
        self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Notes")
        self.guard.adjudicate_substitution(m)
        self.assertEqual(self.guard.get_mandate_status(m), "APPROVED")

        res = self.guard.confirm_purchase(m)
        self.assertTrue(res)
        self.assertEqual(self.guard.get_mandate_status(m), "EXECUTED")

    def test_case_6_authorized_agent_confirms_purchase_accepted(self):
        """Case 6: Explicitly authorized agent confirms approved purchase."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent=self.agent)
        self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Notes")
        self.guard.adjudicate_substitution(m)
        self.assertEqual(self.guard.get_mandate_status(m), "APPROVED")

        mock_gl.message.sender_address = Address(self.agent)
        res = self.guard.confirm_purchase(m)
        self.assertTrue(res)
        self.assertEqual(self.guard.get_mandate_status(m), "EXECUTED")

    def test_case_7_unrelated_account_changes_authorized_agent_rejected(self):
        """Case 7: Unrelated account cannot set or modify authorized agent; storage unchanged."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent=self.agent)

        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(PermissionError):
            self.guard.set_authorized_agent(m, self.intruder)

        # Verify delegation was not hijacked
        mandate_data = json.loads(self.guard.get_mandate(m))
        self.assertEqual(mandate_data["authorized_agent"], self.agent)

    def test_case_8_former_agent_acts_after_revocation_rejected(self):
        """Case 8: Buyer revokes authorized agent; former agent cannot propose or confirm."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent=self.former_agent)

        # Buyer revokes former agent
        self.guard.set_authorized_agent(m, "")
        mandate_data = json.loads(self.guard.get_mandate(m))
        self.assertEqual(mandate_data["authorized_agent"], "")

        # Former agent tries to propose substitution -> rejected
        mock_gl.message.sender_address = Address(self.former_agent)
        with self.assertRaises(PermissionError):
            self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Attempt")

        self.assertEqual(self.guard.get_mandate_status(m), "ACTIVE")

    def test_case_9_unrelated_account_overrides_buyer_decision_rejected(self):
        """Case 9: Unrelated account cannot submit a decision override."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "PREFERRED", "NEW_ONLY", authorized_agent=self.agent)
        self.guard.propose_substitution(m, "Off-Brand", self.url_honest, 8000, "Notes")

        mock_gl.eq_principle.mock_response = json.dumps({
            "decision": "NEEDS_USER_APPROVAL",
            "vendor_price_cents": 8000,
            "stock_status": "IN_STOCK",
            "condition": "NEW",
            "verbatim_quote": "\"price_cents\": 8999",
            "rationale": "Soft brand preference deviation"
        })
        self.guard.adjudicate_substitution(m)
        self.assertEqual(self.guard.get_mandate_status(m), "NEEDS_USER_APPROVAL")

        # Intruder tries to override
        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(PermissionError):
            self.guard.buyer_override(m, approve=True)

        self.assertEqual(self.guard.get_mandate_status(m), "NEEDS_USER_APPROVAL")

    def test_case_10_address_validation_enforced(self):
        """Case 10: Invalid address formats are strictly rejected."""
        mock_gl.message.sender_address = Address(self.buyer)
        # Invalid address string in create_mandate
        with self.assertRaises(ValueError):
            self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent="invalid_address")

        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")
        # Invalid address in set_authorized_agent
        with self.assertRaises(ValueError):
            self.guard.set_authorized_agent(m, "0x123nothex")

    # =========================================================================
    # CORE BUSINESS LOGIC TESTS
    # =========================================================================

    def test_adjudicate_catches_downgraded_and_refurbished_abuse(self):
        self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="ANY",
            condition_rule="NEW_ONLY",
            authorized_agent=self.agent
        )
        mock_gl.message.sender_address = Address(self.agent)
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
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="ANY",
            condition_rule="NEW_ONLY",
            authorized_agent=self.agent
        )
        mock_gl.message.sender_address = Address(self.agent)
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
            condition_rule="NEW_ONLY",
            authorized_agent=self.agent
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Crucial P5 Plus",
            vendor_url=self.url_honest,
            proposed_price_cents=8999,
            agent_notes="Honest specs"
        )

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

    def test_cancellation_access_control(self):
        self.guard.create_mandate(
            target_item="SSD",
            max_budget_cents=10000,
            required_specs="1TB",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(PermissionError):
            self.guard.cancel_mandate(1)

        mock_gl.message.sender_address = Address(self.buyer)
        self.guard.cancel_mandate(1)
        self.assertEqual(self.guard.get_mandate_status(1), "CANCELLED")


if __name__ == "__main__":
    unittest.main()
