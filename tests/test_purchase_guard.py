"""
Unit tests for PurchaseGuard Intelligent Contract.
Mocks the GenLayer runtime environment (gl, TreeMap, u256, Address, gl.vm, gl.nondet)
to verify:
- Dual-role Leader/Validator Equivalence Principle consensus (gl.vm.run_nondet_unsafe)
- Mandate authorization controls & anti-takeover invariants
- Independent vendor evidence acquisition & raw-text verbatim quote validation
- Deterministic clamps for stock availability, non-downgraded condition, and budget ceilings
- Clearing of stale adjudications and audit trail updates on buyer override
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
        self.mock_prompt_response = None

    def exec_prompt(self, prompt, response_format=None):
        if self.mock_prompt_response is not None:
            return self.mock_prompt_response

        if "Generic Low-End SATA" in prompt or "Cheap Drive" in prompt:
            return json.dumps({
                "decision": "REJECTED",
                "vendor_price_cents": 4500,
                "stock_status": "IN_STOCK",
                "condition": "REFURBISHED",
                "verbatim_quote": "\"condition\": \"REFURBISHED\"",
                "rationale": "Product is refurbished and downgraded to SATA speeds, violating NEW_ONLY and NVMe specs."
            })
        elif "14999" in prompt or "Surged SSD" in prompt:
            return json.dumps({
                "decision": "REJECTED",
                "vendor_price_cents": 14999,
                "stock_status": "IN_STOCK",
                "condition": "NEW",
                "verbatim_quote": "\"price_cents\": 14999",
                "rationale": "Actual vendor price of $149.99 exceeds buyer max budget ceiling."
            })
        elif "Off-Brand" in prompt:
            return json.dumps({
                "decision": "NEEDS_USER_APPROVAL",
                "vendor_price_cents": 8000,
                "stock_status": "IN_STOCK",
                "condition": "NEW",
                "verbatim_quote": "\"price_cents\": 8999",
                "rationale": "Soft brand preference deviation."
            })
        elif "Crucial P5 Plus" in prompt:
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


class MockVMReturn:
    def __init__(self, calldata):
        self.calldata = calldata


class MockVM:
    Return = MockVMReturn

    def __init__(self):
        self.tamper_leader = False
        self.tampered_payload = None

    def run_nondet_unsafe(self, leader_fn, validator_fn):
        if self.tamper_leader:
            leader_output = self.tampered_payload
        else:
            leader_output = leader_fn()

        wrapped = MockVMReturn(leader_output)
        valid = validator_fn(wrapped)
        if not valid:
            raise Exception("Consensus failed: validator rejected leader output")
        return leader_output


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
        self.vm = MockVM()
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
        mock_gl.nondet.mock_prompt_response = None
        mock_gl.vm.tamper_leader = False
        mock_gl.vm.tampered_payload = None

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
    # STEWARD & REVIEWER AUTHORIZATION SUITE (9 CORE SCENARIOS)
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
        with self.assertRaises(ValueError):
            self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY", authorized_agent="invalid_address")

        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")
        with self.assertRaises(ValueError):
            self.guard.set_authorized_agent(m, "0x123nothex")

    # =========================================================================
    # CHATGPT REVIEW HARDENING TESTS: VERIFICATION, CLAMPS, STALENESS & OVERRIDE
    # =========================================================================

    def test_hallucinated_quote_not_in_evidence_is_clamped_to_rejected(self):
        """Critical Fix 1: Verbatim quote not present in fetched evidence clamps to REJECTED."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")
        self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Notes")

        # AI invents a plausible quote that does NOT exist in vendor payload
        mock_gl.nondet.mock_prompt_response = json.dumps({
            "decision": "APPROVED",
            "vendor_price_cents": 8999,
            "stock_status": "IN_STOCK",
            "condition": "NEW",
            "verbatim_quote": "\"completely_fake_hallucinated_field\": true",
            "rationale": "Looks verified"
        })

        with self.assertRaises(Exception) as ctx:
            self.guard.adjudicate_substitution(m)
        self.assertIn("verbatim-grounded vendor judgment", str(ctx.exception))

    def test_unknown_or_missing_stock_or_condition_cannot_pass(self):
        """Critical Fix 2: Unknown stock status or condition clamps to REJECTED."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")
        self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Notes")

        # AI tries to approve while stock is OUT_OF_STOCK
        mock_gl.nondet.mock_prompt_response = json.dumps({
            "decision": "APPROVED",
            "vendor_price_cents": 8999,
            "stock_status": "OUT_OF_STOCK",
            "condition": "NEW",
            "verbatim_quote": "\"price_cents\": 8999",
            "rationale": "Great deal but out of stock"
        })

        res = self.guard.adjudicate_substitution(m)
        parsed = json.loads(res)
        self.assertEqual(parsed["decision"], "REJECTED")
        self.assertIn("not in stock", parsed["rationale"])

    def test_weak_vendor_url_validation_rejected(self):
        """Important Fix 4: Non-HTTPS or oversized vendor URLs are rejected."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")

        # Insecure HTTP
        with self.assertRaises(ValueError) as ctx1:
            self.guard.propose_substitution(m, "Drive", "http://insecure-vendor.com/item", 8999, "Notes")
        self.assertIn("HTTPS", str(ctx1.exception))

        # Oversized URL (>256 chars)
        oversized = "https://example.com/" + "a" * 250
        with self.assertRaises(ValueError) as ctx2:
            self.guard.propose_substitution(m, "Drive", oversized, 8999, "Notes")
        self.assertIn("256 character limit", str(ctx2.exception))

    def test_reproposing_clears_stale_adjudication(self):
        """Minor Fix 5A: Stale adjudication record is cleared when re-proposing."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")

        # First proposal gets rejected
        self.guard.propose_substitution(m, "Cheap Drive", self.url_downgraded, 4500, "Notes")
        self.guard.adjudicate_substitution(m)
        self.assertEqual(self.guard.get_mandate_status(m), "REJECTED")
        self.assertIn("REJECTED", self.guard.get_adjudication(m))

        # Re-propose: Stale adjudication must be cleared
        self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Replacement proposal")
        self.assertEqual(self.guard.get_mandate_status(m), "PROPOSED")
        self.assertEqual(self.guard.get_adjudication(m), f"Adjudication not found for mandate: {m}")

    def test_buyer_override_updates_audit_trail(self):
        """Minor Fix 5B: Buyer override updates both mandate status and stored adjudication record."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "PREFERRED", "NEW_ONLY")
        self.guard.propose_substitution(m, "Off-Brand", self.url_honest, 8000, "Notes")
        self.guard.adjudicate_substitution(m)
        self.assertEqual(self.guard.get_mandate_status(m), "NEEDS_USER_APPROVAL")

        # Buyer overrides to APPROVED
        self.guard.buyer_override(m, approve=True)
        self.assertEqual(self.guard.get_mandate_status(m), "APPROVED")

        # Verify audit trail in adjudication record
        adj_data = json.loads(self.guard.get_adjudication(m))
        self.assertEqual(adj_data["decision"], "APPROVED")
        self.assertEqual(adj_data["overridden_by"], self.buyer)
        self.assertIn("Manual override by buyer", adj_data["override_rationale"])

    def test_validator_rejects_malicious_leader(self):
        """Important Fix 3: Validator independently evaluates and rejects a malicious leader."""
        mock_gl.message.sender_address = Address(self.buyer)
        m = self.guard.create_mandate("SSD", 10000, "1TB", "ANY", "NEW_ONLY")
        self.guard.propose_substitution(m, "Crucial P5 Plus", self.url_honest, 8999, "Notes")

        # Malicious leader attempts to force an ungrounded REJECTED verdict
        mock_gl.vm.tamper_leader = True
        mock_gl.vm.tampered_payload = {
            "status": "OK",
            "decision": "REJECTED",
            "vendor_price_cents": 8999,
            "stock_status": "IN_STOCK",
            "condition": "NEW",
            "verbatim_quote": "\"price_cents\": 8999",
            "rationale": "Malicious leader veto",
            "fetched_text": "..."
        }

        # Validator re-derives consensus independently; discrepancy causes consensus failure
        with self.assertRaises(Exception) as ctx:
            self.guard.adjudicate_substitution(m)
        self.assertIn("validator rejected leader output", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
