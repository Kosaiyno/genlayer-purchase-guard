# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import typing
import json

class PurchaseGuard(gl.Contract):
    """
    PurchaseGuard is a production-grade GenLayer Intelligent Contract primitive
    designed for the autonomous AI agent economy.

    Core Purpose:
    When an AI procurement or shopping agent attempts to fulfill a purchase order
    and the target product is unavailable, out-of-stock, or price-surged, traditional
    smart contracts cannot evaluate whether an alternative product is functionally,
    technically, and economically equivalent.

    PurchaseGuard acts as an autonomous on-chain guardrail:
    1. Purchase Mandate Escrow: Buyers define target products, budget ceilings, specification floors,
       brand rules (STRICT, PREFERRED, ANY), and condition rules (NEW_ONLY, REFURBISHED_OK).
    2. Agent Substitution Proposal: Autonomous agents propose alternatives with price and spec evidence.
    3. Multi-Pillar Equivalence Adjudication: GenLayer validators independently evaluate specification
       parity, brand compliance, and budget limits to reach consensus on:
       - APPROVED: Meets/exceeds specifications within budget limits.
       - NEEDS_USER_APPROVAL: Equivalent product but deviates on soft brand or style preferences.
       - REJECTED: Fails key specs, downgrades performance/capacity, or exceeds budget ceiling.
    4. Lifecycle Management & Dispute Overrides: Buyers can override borderline proposals or cancel unfulfilled mandates.
    """
    owner: Address
    mandate_counter: u256
    mandates: TreeMap[u256, str]
    proposals: TreeMap[u256, str]
    adjudications: TreeMap[u256, str]

    def __init__(self):
        self.owner = gl.message.sender_address
        self.mandate_counter = u256(0)

    @gl.public.view
    def get_guard_stats(self) -> str:
        return (
            "PurchaseGuard Owner: " + str(self.owner)
            + " | Total Mandates Registered: " + str(self.mandate_counter)
        )

    @gl.public.view
    def get_total_mandates(self) -> u256:
        return self.mandate_counter

    @gl.public.view
    def get_mandate(self, mandate_id: int) -> str:
        m_key = u256(mandate_id)
        if m_key in self.mandates:
            return str(self.mandates[m_key])
        return "Mandate not found: " + str(mandate_id)

    @gl.public.view
    def get_proposal(self, mandate_id: int) -> str:
        m_key = u256(mandate_id)
        if m_key in self.proposals:
            return str(self.proposals[m_key])
        return "Proposal not found for mandate: " + str(mandate_id)

    @gl.public.view
    def get_adjudication(self, mandate_id: int) -> str:
        m_key = u256(mandate_id)
        if m_key in self.adjudications:
            return str(self.adjudications[m_key])
        return "Adjudication not found for mandate: " + str(mandate_id)

    @gl.public.view
    def get_mandate_status(self, mandate_id: int) -> str:
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            return "UNKNOWN"
        try:
            data = json.loads(self.mandates[m_key])
            return str(data.get("status", "UNKNOWN"))
        except Exception:
            return "UNKNOWN"

    @gl.public.write
    def create_mandate(
        self,
        target_item: str,
        max_budget_cents: int,
        required_specs: str,
        brand_rule: str,
        condition_rule: str
    ) -> u256:
        clean_target = str(target_item).strip()
        clean_specs = str(required_specs).strip()
        clean_brand = str(brand_rule).upper().strip()
        clean_cond = str(condition_rule).upper().strip()

        if len(clean_target) == 0:
            raise ValueError("Target item name cannot be empty")
        if max_budget_cents <= 0:
            raise ValueError("Maximum budget must be greater than zero")
        if len(clean_specs) == 0:
            raise ValueError("Required specifications cannot be empty")
        if clean_brand not in ["STRICT", "PREFERRED", "ANY"]:
            raise ValueError("Brand rule must be STRICT, PREFERRED, or ANY")
        if clean_cond not in ["NEW_ONLY", "REFURBISHED_OK"]:
            raise ValueError("Condition rule must be NEW_ONLY or REFURBISHED_OK")

        new_id = u256(int(self.mandate_counter) + 1)
        self.mandate_counter = new_id

        created_ts = 0
        try:
            created_ts = int(gl.block.timestamp)
        except Exception:
            pass

        mandate_record = {
            "mandate_id": int(new_id),
            "buyer": str(gl.message.sender_address),
            "target_item": clean_target,
            "max_budget_cents": int(max_budget_cents),
            "required_specs": clean_specs,
            "brand_rule": clean_brand,
            "condition_rule": clean_cond,
            "status": "ACTIVE",
            "created_at": created_ts
        }

        self.mandates[new_id] = json.dumps(mandate_record)
        return new_id

    @gl.public.write
    def propose_substitution(
        self,
        mandate_id: int,
        substitute_item: str,
        proposed_price_cents: int,
        item_specs: str,
        reason_unavailable: str,
        vendor_url: str
    ) -> bool:
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        current_status = mandate.get("status", "")
        if current_status not in ["ACTIVE", "REJECTED"]:
            raise ValueError(f"Cannot submit proposal for mandate in status '{current_status}'")

        clean_sub = str(substitute_item).strip()
        clean_specs = str(item_specs).strip()
        clean_reason = str(reason_unavailable).strip()
        clean_url = str(vendor_url).strip()

        if len(clean_sub) == 0:
            raise ValueError("Substitute item name cannot be empty")
        if proposed_price_cents <= 0:
            raise ValueError("Proposed price must be greater than zero")
        if len(clean_specs) == 0:
            raise ValueError("Item specifications cannot be empty")

        proposal_record = {
            "mandate_id": int(mandate_id),
            "agent_address": str(gl.message.sender_address),
            "substitute_item": clean_sub,
            "proposed_price_cents": int(proposed_price_cents),
            "item_specs": clean_specs,
            "reason_unavailable": clean_reason if clean_reason else "Original item out of stock",
            "vendor_url": clean_url if clean_url else "N/A"
        }

        self.proposals[m_key] = json.dumps(proposal_record)
        mandate["status"] = "PROPOSED"
        self.mandates[m_key] = json.dumps(mandate)
        return True

    @gl.public.write
    def adjudicate_substitution(self, mandate_id: int) -> str:
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")
        if m_key not in self.proposals:
            raise ValueError(f"No substitution proposal submitted for mandate {mandate_id}")

        mandate = json.loads(self.mandates[m_key])
        if mandate.get("status") != "PROPOSED":
            raise ValueError(f"Mandate is in status '{mandate.get('status')}', expected 'PROPOSED'")

        proposal = json.loads(self.proposals[m_key])

        max_budget = mandate["max_budget_cents"]
        proposed_price = proposal["proposed_price_cents"]
        budget_overrun = proposed_price > max_budget

        def get_input() -> str:
            return (
                f"=== BUYER PURCHASE MANDATE ===\n"
                f"Mandate ID: {mandate_id}\n"
                f"Target Product: {mandate['target_item']}\n"
                f"Maximum Budget: ${max_budget / 100:.2f} ({max_budget} cents)\n"
                f"Required Specifications: {mandate['required_specs']}\n"
                f"Brand Rule: {mandate['brand_rule']}\n"
                f"Condition Rule: {mandate['condition_rule']}\n\n"
                f"=== AGENT PROPOSED SUBSTITUTION ===\n"
                f"Proposed Alternative: {proposal['substitute_item']}\n"
                f"Proposed Price: ${proposed_price / 100:.2f} ({proposed_price} cents)\n"
                f"Alternative Specifications: {proposal['item_specs']}\n"
                f"Reason Original Unavailable: {proposal['reason_unavailable']}\n"
                f"Vendor Evidence: {proposal['vendor_url']}\n\n"
                f"=== ADJUDICATION DIRECTIVES ===\n"
                f"1. Budget Check: If proposed price exceeds maximum budget (${max_budget / 100:.2f}), decision MUST be REJECTED.\n"
                f"2. Parity Check: If substitute matches or exceeds functional requirements within budget, decision is APPROVED.\n"
                f"3. Preference Drift: If substitute is a functional equivalent but deviates from preferred brand, decision is NEEDS_USER_APPROVAL.\n"
                f"4. Spec Downgrade: If key technical specifications (capacity, speed, connectivity, condition) are downgraded, decision is REJECTED."
            )

        raw_result = gl.eq_principle.prompt_non_comparative(
            get_input,
            task=(
                f"Act as an impartial commercial procurement arbiter. Evaluate the proposed alternative "
                f"'{proposal['substitute_item']}' against the buyer mandate for '{mandate['target_item']}'. "
                f"Output a valid JSON object with keys: "
                f"'decision' ('APPROVED', 'NEEDS_USER_APPROVAL', or 'REJECTED'), "
                f"'spec_score' (integer 0-100), "
                f"'price_compliance' (boolean), "
                f"'rationale' (concise 1-2 sentence explanation)."
            ),
            criteria="""
                1. The output is a valid JSON object with keys: decision, spec_score, price_compliance, and rationale.
                2. The decision is exactly one of: APPROVED, NEEDS_USER_APPROVAL, or REJECTED.
                3. If the proposed price exceeds the maximum budget, price_compliance is false and decision is REJECTED.
                4. If the substitute matches or exceeds all required specifications within budget, decision is APPROVED.
                5. If specifications are equivalent but deviate from preferred brands or soft preferences, decision is NEEDS_USER_APPROVAL.
                6. If key specifications are degraded or condition requirements are breached, decision is REJECTED.
            """,
        )

        result_str = str(raw_result).strip()

        # Sanitize markdown code blocks if returned
        clean_json_str = result_str
        if "```" in clean_json_str:
            first_brace = clean_json_str.find("{")
            last_brace = clean_json_str.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                clean_json_str = clean_json_str[first_brace : last_brace + 1]
        elif not clean_json_str.startswith("{"):
            first_brace = clean_json_str.find("{")
            last_brace = clean_json_str.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                clean_json_str = clean_json_str[first_brace : last_brace + 1]

        decision = "NEEDS_USER_APPROVAL"
        try:
            parsed = json.loads(clean_json_str)
            raw_decision = str(parsed.get("decision", "NEEDS_USER_APPROVAL")).upper().strip()
            if raw_decision in ["APPROVED", "NEEDS_USER_APPROVAL", "REJECTED"]:
                decision = raw_decision
        except Exception:
            decision = "NEEDS_USER_APPROVAL"

        # Deterministic safety clamp: Hard budget overruns can never be APPROVED
        if budget_overrun and decision == "APPROVED":
            decision = "REJECTED"

        # Update mandate state
        mandate["status"] = decision
        self.mandates[m_key] = json.dumps(mandate)
        self.adjudications[m_key] = clean_json_str

        return clean_json_str

    @gl.public.write
    def confirm_purchase(self, mandate_id: int) -> bool:
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        if mandate.get("status") != "APPROVED":
            raise ValueError(f"Cannot confirm purchase: mandate status is '{mandate.get('status')}', must be 'APPROVED'")

        mandate["status"] = "EXECUTED"
        self.mandates[m_key] = json.dumps(mandate)
        return True

    @gl.public.write
    def buyer_override(self, mandate_id: int, approve: bool) -> bool:
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        caller_str = str(gl.message.sender_address)
        if caller_str != mandate.get("buyer"):
            raise Exception("Unauthorized: Only the original mandate buyer can submit a decision override")

        if mandate.get("status") != "NEEDS_USER_APPROVAL":
            raise ValueError(f"Cannot override mandate in status '{mandate.get('status')}', must be 'NEEDS_USER_APPROVAL'")

        mandate["status"] = "APPROVED" if approve else "REJECTED"
        self.mandates[m_key] = json.dumps(mandate)
        return True

    @gl.public.write
    def cancel_mandate(self, mandate_id: int) -> bool:
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        caller_str = str(gl.message.sender_address)
        if caller_str != mandate.get("buyer") and caller_str != str(self.owner):
            raise Exception("Unauthorized: Only the buyer or contract owner can cancel a mandate")

        if mandate.get("status") == "EXECUTED":
            raise ValueError("Cannot cancel an already EXECUTED purchase mandate")

        mandate["status"] = "CANCELLED"
        self.mandates[m_key] = json.dumps(mandate)
        return True
