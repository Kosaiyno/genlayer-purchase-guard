"""
Unit tests for PurchaseGuard Intelligent Contract.
Mocks the GenLayer runtime environment (gl, TreeMap, u256, Address) to verify
all contract state transitions, access controls, equivalence logic, and edge cases.
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


class MockEqPrinciple:
    def __init__(self):
        self.mock_response = None

    def prompt_non_comparative(self, get_input_fn, task="", criteria=""):
        # If a custom mock response is provided, return it
        if self.mock_response is not None:
            return self.mock_response
        
        # Default mock procurement logic based on prompt content
        user_input = get_input_fn()
        if "Proposed Price: $120.00 (12000 cents)" in user_input and "Maximum Budget: $100.00" in user_input:
            return json.dumps({
                "decision": "REJECTED",
                "spec_score": 60,
                "price_compliance": False,
                "rationale": "Proposed price exceeds the buyer's maximum budget ceiling."
            })
        elif "Crucial P5 Plus" in user_input:
            return json.dumps({
                "decision": "APPROVED",
                "spec_score": 95,
                "price_compliance": True,
                "rationale": "High-speed PCIe 4.0 NVMe SSD matches buyer capacity and speed requirements within budget."
            })
        elif "Kingston NV2" in user_input:
            return json.dumps({
                "decision": "NEEDS_USER_APPROVAL",
                "spec_score": 82,
                "price_compliance": True,
                "rationale": "Budget PCIe 4.0 drive meets capacity but deviates from buyer's preferred high-end performance tier."
            })
        else:
            return json.dumps({
                "decision": "APPROVED",
                "spec_score": 90,
                "price_compliance": True,
                "rationale": "Acceptable functional equivalent."
            })


class MockContract:
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        # Initialize GenLayer persistent storage containers
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
        # Reset caller to default buyer
        mock_gl.message.sender_address = Address("0xBuyer11111111111111111111111111111111111")
        mock_gl.eq_principle.mock_response = None
        self.guard = PurchaseGuard()
        self.buyer = "0xBuyer11111111111111111111111111111111111"
        self.agent = "0xAgent22222222222222222222222222222222222"
        self.intruder = "0xIntruder9999999999999999999999999999999"

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

        mandate_json = json.loads(self.guard.get_mandate(1))
        self.assertEqual(mandate_json["target_item"], "Samsung 980 Pro 1TB NVMe SSD")
        self.assertEqual(mandate_json["max_budget_cents"], 10000)
        self.assertEqual(mandate_json["brand_rule"], "PREFERRED")
        self.assertEqual(mandate_json["condition_rule"], "NEW_ONLY")

    def test_create_mandate_validations(self):
        # Empty target item
        with self.assertRaises(ValueError):
            self.guard.create_mandate("", 10000, "1TB SSD", "ANY", "NEW_ONLY")

        # Zero or negative budget
        with self.assertRaises(ValueError):
            self.guard.create_mandate("SSD", 0, "1TB SSD", "ANY", "NEW_ONLY")
        with self.assertRaises(ValueError):
            self.guard.create_mandate("SSD", -500, "1TB SSD", "ANY", "NEW_ONLY")

        # Invalid brand rule
        with self.assertRaises(ValueError):
            self.guard.create_mandate("SSD", 10000, "1TB SSD", "INVALID_BRAND", "NEW_ONLY")

        # Invalid condition rule
        with self.assertRaises(ValueError):
            self.guard.create_mandate("SSD", 10000, "1TB SSD", "ANY", "USED_OK")

    def test_propose_substitution(self):
        mandate_id = self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0 read >= 7000MB/s",
            brand_rule="PREFERRED",
            condition_rule="NEW_ONLY"
        )

        # Agent submits proposal
        mock_gl.message.sender_address = Address(self.agent)
        res = self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Crucial P5 Plus 1TB NVMe SSD",
            proposed_price_cents=8999,
            item_specs="1TB NVMe M.2 SSD PCIe 4.0 read 6600MB/s New",
            reason_unavailable="Samsung 980 Pro out of stock at major distributors",
            vendor_url="https://amazon.com/dp/B098WKQRDL"
        )
        self.assertTrue(res)
        self.assertEqual(self.guard.get_mandate_status(1), "PROPOSED")

        prop_json = json.loads(self.guard.get_proposal(1))
        self.assertEqual(prop_json["substitute_item"], "Crucial P5 Plus 1TB NVMe SSD")
        self.assertEqual(prop_json["proposed_price_cents"], 8999)
        self.assertEqual(prop_json["agent_address"], self.agent)

    def test_adjudicate_approved_and_confirm(self):
        mandate_id = self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0 read >= 7000MB/s",
            brand_rule="PREFERRED",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Crucial P5 Plus 1TB NVMe SSD",
            proposed_price_cents=8999,
            item_specs="1TB NVMe M.2 SSD PCIe 4.0 read 6600MB/s New",
            reason_unavailable="Out of stock",
            vendor_url="https://vendor.com/crucial-p5"
        )

        # Consensus adjudication
        adj_result = self.guard.adjudicate_substitution(1)
        parsed_adj = json.loads(adj_result)
        self.assertEqual(parsed_adj["decision"], "APPROVED")
        self.assertEqual(self.guard.get_mandate_status(1), "APPROVED")

        # Confirm purchase
        confirm_res = self.guard.confirm_purchase(1)
        self.assertTrue(confirm_res)
        self.assertEqual(self.guard.get_mandate_status(1), "EXECUTED")

        # Cannot cancel once EXECUTED
        mock_gl.message.sender_address = Address(self.buyer)
        with self.assertRaises(ValueError):
            self.guard.cancel_mandate(1)

    def test_adjudicate_budget_clamp_rejection(self):
        mandate_id = self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,  # $100.00
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Corsair MP600 Pro 1TB NVMe SSD",
            proposed_price_cents=12000,  # $120.00 (Exceeds budget!)
            item_specs="1TB NVMe PCIe 4.0 read 7100MB/s",
            reason_unavailable="Only premium available",
            vendor_url="https://vendor.com/corsair"
        )

        # Even if LLM erroneously tries to return APPROVED, deterministic safety clamp enforces REJECTED
        mock_gl.eq_principle.mock_response = json.dumps({
            "decision": "APPROVED",
            "spec_score": 98,
            "price_compliance": False,
            "rationale": "High quality alternative."
        })

        self.guard.adjudicate_substitution(1)
        # Mandate status should be clamped to REJECTED
        self.assertEqual(self.guard.get_mandate_status(1), "REJECTED")

        # Cannot confirm purchase on rejected mandate
        with self.assertRaises(ValueError):
            self.guard.confirm_purchase(1)

    def test_adjudicate_needs_user_approval_and_buyer_override(self):
        mandate_id = self.guard.create_mandate(
            target_item="Samsung 980 Pro 1TB NVMe SSD",
            max_budget_cents=10000,
            required_specs="1TB NVMe M.2 SSD PCIe 4.0",
            brand_rule="PREFERRED",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(
            mandate_id=1,
            substitute_item="Kingston NV2 1TB NVMe SSD",
            proposed_price_cents=5999,
            item_specs="1TB NVMe PCIe 4.0 Entry Tier",
            reason_unavailable="Flagship drives out of stock",
            vendor_url="https://vendor.com/kingston"
        )

        # Adjudication returns NEEDS_USER_APPROVAL
        self.guard.adjudicate_substitution(1)
        self.assertEqual(self.guard.get_mandate_status(1), "NEEDS_USER_APPROVAL")

        # Non-buyer cannot override
        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(Exception):
            self.guard.buyer_override(1, approve=True)

        # Buyer approves override
        mock_gl.message.sender_address = Address(self.buyer)
        self.guard.buyer_override(1, approve=True)
        self.assertEqual(self.guard.get_mandate_status(1), "APPROVED")

        # Now purchase can be confirmed
        self.guard.confirm_purchase(1)
        self.assertEqual(self.guard.get_mandate_status(1), "EXECUTED")

    def test_cancel_mandate_access_control(self):
        mandate_id = self.guard.create_mandate(
            target_item="Office Chair Ergonomic",
            max_budget_cents=25000,
            required_specs="Lumbar support, mesh back, 3D armrests",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        # Intruder attempts to cancel
        mock_gl.message.sender_address = Address(self.intruder)
        with self.assertRaises(Exception):
            self.guard.cancel_mandate(1)

        # Buyer cancels
        mock_gl.message.sender_address = Address(self.buyer)
        self.guard.cancel_mandate(1)
        self.assertEqual(self.guard.get_mandate_status(1), "CANCELLED")

    def test_owner_can_cancel(self):
        mandate_id = self.guard.create_mandate(
            target_item="Mechanical Keyboard",
            max_budget_cents=12000,
            required_specs="Hot-swappable switches, wireless",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        # Contract owner (0xBuyer... in this setup is also deployer)
        self.guard.cancel_mandate(1)
        self.assertEqual(self.guard.get_mandate_status(1), "CANCELLED")

    def test_nonexistent_mandate_errors(self):
        with self.assertRaises(ValueError):
            self.guard.propose_substitution(999, "Sub", 100, "Specs", "Reason", "http")
        with self.assertRaises(ValueError):
            self.guard.adjudicate_substitution(999)
        with self.assertRaises(ValueError):
            self.guard.confirm_purchase(999)
        with self.assertRaises(ValueError):
            self.guard.buyer_override(999, approve=True)
        with self.assertRaises(ValueError):
            self.guard.cancel_mandate(999)

        self.assertIn("Mandate not found: 999", self.guard.get_mandate(999))
        self.assertIn("Proposal not found for mandate: 999", self.guard.get_proposal(999))
        self.assertIn("Adjudication not found for mandate: 999", self.guard.get_adjudication(999))
        self.assertEqual(self.guard.get_mandate_status(999), "UNKNOWN")

    def test_markdown_wrapped_response_sanitization(self):
        mandate_id = self.guard.create_mandate(
            target_item="USB-C Hub",
            max_budget_cents=5000,
            required_specs="4K 60Hz HDMI, 100W PD",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        self.guard.propose_substitution(1, "Anker USB-C Hub", 4500, "4K 60Hz HDMI, 100W PD", "Original OOS", "http")

        # Simulate LLM returning markdown code block ```json ... ```
        mock_gl.eq_principle.mock_response = """```json
{
  "decision": "APPROVED",
  "spec_score": 96,
  "price_compliance": true,
  "rationale": "Matches all required port specs under budget."
}
```"""
        result = self.guard.adjudicate_substitution(1)
        parsed = json.loads(result)
        self.assertEqual(parsed["decision"], "APPROVED")
        self.assertEqual(self.guard.get_mandate_status(1), "APPROVED")

    def test_repropose_after_rejection(self):
        mandate_id = self.guard.create_mandate(
            target_item="Gaming Mouse",
            max_budget_cents=7000,
            required_specs="Optical sensor, wireless, < 70g",
            brand_rule="ANY",
            condition_rule="NEW_ONLY"
        )
        mock_gl.message.sender_address = Address(self.agent)
        # 1st proposal: Exceeds budget
        self.guard.propose_substitution(1, "Expensive Mouse", 9500, "Wireless 65g", "Stock issue", "http")
        self.guard.adjudicate_substitution(1)
        self.assertEqual(self.guard.get_mandate_status(1), "REJECTED")

        # Agent submits a 2nd, compliant proposal
        mock_gl.eq_principle.mock_response = json.dumps({
            "decision": "APPROVED",
            "spec_score": 92,
            "price_compliance": True,
            "rationale": "Affordable wireless mouse fits budget and weight criteria."
        })
        self.guard.propose_substitution(1, "Budget Light Mouse", 5500, "Wireless 68g", "Found cheaper alternative", "http")
        self.assertEqual(self.guard.get_mandate_status(1), "PROPOSED")
        self.guard.adjudicate_substitution(1)
        self.assertEqual(self.guard.get_mandate_status(1), "APPROVED")


if __name__ == "__main__":
    unittest.main()

