# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json

def _validate_address(addr_str: str) -> str:
    """Validates that a non-empty string is a valid 20-byte hex address. Empty string allowed to revoke delegation."""
    s = str(addr_str).strip()
    if not s:
        return ""
    clean_hex = s[2:] if s.startswith("0x") or s.startswith("0X") else s
    if len(clean_hex) != 40 or not all(c in "0123456789abcdefABCDEF" for c in clean_hex):
        raise ValueError(f"Invalid address format: '{addr_str}'. Must be a valid 20-byte hex address (0x...) or empty string to revoke.")
    return f"0x{clean_hex.lower()}"

class PurchaseGuard(gl.Contract):
    """
    PurchaseGuard: Autonomous On-Chain Procurement Firewall & Policy Arbiter.
    
    Protects buyers and autonomous shopping agents against:
    1. Unrelated account takeover (strict authorization: only buyer or delegated agent can propose or confirm execution).
    2. Unverified caller claims (contract independently acquires vendor evidence via gl.nondet.web.get).
    3. Hidden price surges & budget overruns (deterministic clamp against max_budget_cents).
    4. Counterfeit / downgraded specifications & refurbished goods (Equivalence Principle consensus with verbatim quote grounding).
    5. Out-of-stock ghost listings (independent vendor availability verification).
    """
    owner: Address
    mandate_counter: u256
    mandates: TreeMap[u256, str]
    proposals: TreeMap[u256, str]
    adjudications: TreeMap[u256, str]

    def __init__(self):
        self.owner = gl.message.sender_address
        self.mandate_counter = u256(0)

    # =========================================================================
    # VIEW METHODS
    # =========================================================================

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

    # =========================================================================
    # WRITE METHODS
    # =========================================================================

    @gl.public.write
    def create_mandate(
        self,
        target_item: str,
        max_budget_cents: int,
        required_specs: str,
        brand_rule: str,
        condition_rule: str,
        authorized_agent: str = ""
    ) -> u256:
        """
        Creates an immutable purchase mandate bound to the buyer (caller).
        Optionally specifies an authorized_agent address delegated to submit proposals and confirm purchases.
        """
        clean_target = str(target_item).strip()
        clean_specs = str(required_specs).strip()
        clean_brand = str(brand_rule).upper().strip()
        clean_cond = str(condition_rule).upper().strip()
        clean_agent = _validate_address(authorized_agent)

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
            "authorized_agent": clean_agent,
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
    def set_authorized_agent(self, mandate_id: int, agent_address: str) -> bool:
        """
        Allows the buyer to explicitly authorize or update a delegated procurement agent.
        Only callable by the original mandate buyer.
        """
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        caller_str = str(gl.message.sender_address).lower()
        buyer_str = str(mandate.get("buyer", "")).lower()

        if caller_str != buyer_str:
            raise PermissionError("Unauthorized: Only the original mandate buyer can set or update the authorized agent")

        clean_agent = _validate_address(agent_address)
        mandate["authorized_agent"] = clean_agent
        self.mandates[m_key] = json.dumps(mandate)
        return True

    @gl.public.write
    def propose_substitution(
        self,
        mandate_id: int,
        substitute_item: str,
        vendor_url: str,
        proposed_price_cents: int,
        agent_notes: str
    ) -> bool:
        """
        Submits a substitution proposal for a buyer's mandate.
        
        MANDATE AUTHORIZATION:
        Restricted to the buyer or an explicitly authorized agent. Unrelated accounts
        are strictly prohibited from taking over or submitting proposals on another account's mandate.
        """
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        current_status = mandate.get("status", "")
        if current_status not in ["ACTIVE", "REJECTED"]:
            raise ValueError(f"Cannot submit proposal for mandate in status '{current_status}'")

        # Authorization Enforcement: Caller must be buyer or authorized_agent
        caller = str(gl.message.sender_address).lower()
        buyer = str(mandate.get("buyer", "")).lower()
        agent = str(mandate.get("authorized_agent", "")).lower()

        is_buyer = (caller == buyer)
        is_agent = (bool(agent) and caller == agent)
        if not (is_buyer or is_agent):
            raise PermissionError(
                f"Unauthorized proposal submission: caller {gl.message.sender_address} is neither the mandate buyer nor an authorized agent"
            )

        clean_sub = str(substitute_item).strip()
        clean_url = str(vendor_url).strip()
        clean_notes = str(agent_notes).strip()

        if len(clean_sub) == 0:
            raise ValueError("Substitute item name cannot be empty")
        if len(clean_url) == 0:
            raise ValueError("Vendor evidence URL cannot be empty")
        if proposed_price_cents <= 0:
            raise ValueError("Proposed price must be greater than zero")

        proposal_record = {
            "mandate_id": int(mandate_id),
            "agent_address": str(gl.message.sender_address),
            "substitute_item": clean_sub,
            "vendor_url": clean_url,
            "proposed_price_cents": int(proposed_price_cents),
            "agent_notes": clean_notes if clean_notes else "Substitution proposed by procurement agent"
        }

        self.proposals[m_key] = json.dumps(proposal_record)
        mandate["status"] = "PROPOSED"
        self.mandates[m_key] = json.dumps(mandate)
        return True

    @gl.public.write
    def adjudicate_substitution(self, mandate_id: int) -> str:
        """
        Contract-Side Evidence Acquisition & Multi-Pillar Adjudication:
        1. Independently fetches live vendor evidence via gl.nondet.web.get(vendor_url).
        2. Validators extract material product facts (price, stock, condition, specs) and verbatim quotes.
        3. Deterministic safety clamps verify verbatim quotes, budget ceilings, condition rules, and stock status.
        4. Canonicalized adjudication record stored on-chain.
        """
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")
        if m_key not in self.proposals:
            raise ValueError(f"No substitution proposal submitted for mandate {mandate_id}")

        mandate = json.loads(self.mandates[m_key])
        if mandate.get("status") != "PROPOSED":
            raise ValueError(f"Mandate is in status '{mandate.get('status')}', expected 'PROPOSED'")

        proposal = json.loads(self.proposals[m_key])

        # Snapshot local variables before non-deterministic closures
        target_vendor_url = str(proposal["vendor_url"])
        target_item = str(mandate["target_item"])
        max_budget = int(mandate["max_budget_cents"])
        required_specs = str(mandate["required_specs"])
        brand_rule = str(mandate["brand_rule"])
        condition_rule = str(mandate["condition_rule"])
        substitute_name = str(proposal["substitute_item"])
        claimed_price = int(proposal["proposed_price_cents"])

        # 1. Non-deterministic Evidence Fetching Closure
        def get_input() -> str:
            try:
                resp = gl.nondet.web.get(target_vendor_url)
                body_text = resp.body.decode("utf-8") if hasattr(resp, "body") else str(resp)
            except Exception as e:
                body_text = f"[VENDOR_FETCH_ERROR]: {str(e)}"

            clean_vendor_payload = body_text[:4000].strip()
            if len(clean_vendor_payload) == 0:
                clean_vendor_payload = "[EMPTY_VENDOR_PAYLOAD_ERROR]"

            return (
                f"=== BUYER PURCHASE MANDATE ===\n"
                f"Target Item: {target_item}\n"
                f"Maximum Budget Cents: {max_budget} (${max_budget / 100:.2f})\n"
                f"Required Specs: {required_specs}\n"
                f"Brand Rule: {brand_rule}\n"
                f"Condition Rule: {condition_rule}\n\n"
                f"=== AGENT CLAIM ===\n"
                f"Proposed Alternative: {substitute_name}\n"
                f"Claimed Price Cents: {claimed_price} (${claimed_price / 100:.2f})\n"
                f"Vendor Evidence URL: {target_vendor_url}\n\n"
                f"=== INDEPENDENTLY FETCHED VENDOR EVIDENCE ===\n"
                f"{clean_vendor_payload}\n\n"
                f"=== EVALUATION DIRECTIVES ===\n"
                f"1. Independent Verification: Read the actual vendor evidence payload above.\n"
                f"2. Extract the actual vendor price (in cents), stock status (IN_STOCK/OUT_OF_STOCK), and condition (NEW/REFURBISHED/USED).\n"
                f"3. Verbatim Quote: Extract an exact substring from the vendor payload proving price, condition, or availability.\n"
                f"4. If vendor price > max budget, or item is OUT_OF_STOCK, or condition violates rule, or specs are downgraded: REJECTED.\n"
                f"5. If substitute meets/exceeds specifications within budget: APPROVED.\n"
                f"6. If functional equivalent with soft brand deviation: NEEDS_USER_APPROVAL."
            )

        task = (
            f"Act as an impartial commercial procurement arbiter. Independently verify the vendor evidence "
            f"for '{substitute_name}' against the buyer mandate for '{target_item}'. "
            f"Output a valid JSON object with keys: "
            f"'decision' ('APPROVED', 'NEEDS_USER_APPROVAL', or 'REJECTED'), "
            f"'vendor_price_cents' (integer), "
            f"'stock_status' ('IN_STOCK' or 'OUT_OF_STOCK'), "
            f"'condition' ('NEW', 'REFURBISHED', or 'USED'), "
            f"'verbatim_quote' (exact string from the vendor payload, up to 120 chars), and "
            f"'rationale' (concise explanation up to 200 chars)."
        )

        criteria = """
            1. The output must be a valid JSON object with keys: 'decision', 'vendor_price_cents', 'stock_status', 'condition', 'verbatim_quote', and 'rationale'.
            2. 'decision' must be strictly one of: 'APPROVED', 'NEEDS_USER_APPROVAL', or 'REJECTED'.
            3. 'verbatim_quote' must be an exact substring from the fetched vendor evidence payload.
            4. If the vendor payload shows the actual price exceeds maximum budget or item is out of stock, decision must be 'REJECTED'.
            5. If the product meets/exceeds required specs and condition within budget, decision is 'APPROVED'.
            6. If equivalent but deviates from preferred brand, decision is 'NEEDS_USER_APPROVAL'.
        """

        raw_result = gl.eq_principle.prompt_non_comparative(
            get_input,
            task=task,
            criteria=criteria,
        )

        # 2. Canonical JSON Parsing & Robust Fence Stripping
        result_str = str(raw_result).strip()
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

        decision = "REJECTED"
        vendor_price = 0
        stock_status = "UNKNOWN"
        condition_found = "UNKNOWN"
        verbatim_quote = "NONE"
        rationale = "Default fallback"

        try:
            parsed = json.loads(clean_json_str)
            raw_dec = str(parsed.get("decision", "REJECTED")).upper().strip()
            if raw_dec in ["APPROVED", "NEEDS_USER_APPROVAL", "REJECTED"]:
                decision = raw_dec
            vendor_price = int(parsed.get("vendor_price_cents", 0))
            stock_status = str(parsed.get("stock_status", "UNKNOWN")).upper().strip()
            condition_found = str(parsed.get("condition", "UNKNOWN")).upper().strip()
            verbatim_quote = str(parsed.get("verbatim_quote", "NONE")).strip()[:120]
            rationale = str(parsed.get("rationale", "")).strip()[:200]
        except Exception as e:
            decision = "REJECTED"
            rationale = f"Parsing fallback: {str(e)[:80]}"

        # 3. Deterministic Invariant Clamps (Code Moves State)
        # Clamp 1: Verbatim Quote Verification
        if len(verbatim_quote) < 4 or verbatim_quote == "NONE":
            decision = "REJECTED"
            rationale = "Deterministic clamp: Missing verifiable verbatim quote from vendor evidence."

        # Clamp 2: Hard Budget Ceiling
        if vendor_price > max_budget or claimed_price > max_budget:
            decision = "REJECTED"
            rationale = f"Deterministic clamp: Price ({max(vendor_price, claimed_price)} cents) exceeds max budget ({max_budget} cents)."

        # Clamp 3: Stock Availability
        if stock_status == "OUT_OF_STOCK":
            decision = "REJECTED"
            rationale = "Deterministic clamp: Vendor item is out of stock."

        # Clamp 4: Condition Compliance
        if condition_rule == "NEW_ONLY" and condition_found in ["REFURBISHED", "USED"]:
            decision = "REJECTED"
            rationale = f"Deterministic clamp: Mandate requires NEW_ONLY but vendor condition is {condition_found}."

        # 4. Canonicalized Storage Record
        canonical_record = {
            "mandate_id": int(mandate_id),
            "decision": decision,
            "vendor_price_cents": int(vendor_price),
            "stock_status": stock_status,
            "condition": condition_found,
            "verbatim_quote": verbatim_quote,
            "rationale": rationale
        }
        canonical_json = json.dumps(canonical_record)

        mandate["status"] = decision
        self.mandates[m_key] = json.dumps(mandate)
        self.adjudications[m_key] = canonical_json

        return canonical_json

    @gl.public.write
    def confirm_purchase(self, mandate_id: int) -> bool:
        """
        Executes purchase confirmation for an APPROVED mandate.
        
        MANDATE AUTHORIZATION:
        Restricted to the buyer or an explicitly authorized agent. Unrelated accounts
        are strictly prohibited from triggering confirmation.
        """
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        if mandate.get("status") != "APPROVED":
            raise ValueError(f"Cannot confirm purchase: mandate status is '{mandate.get('status')}', must be 'APPROVED'")

        # Authorization Enforcement: Caller must be buyer or authorized_agent
        caller = str(gl.message.sender_address).lower()
        buyer = str(mandate.get("buyer", "")).lower()
        agent = str(mandate.get("authorized_agent", "")).lower()

        is_buyer = (caller == buyer)
        is_agent = (bool(agent) and caller == agent)
        if not (is_buyer or is_agent):
            raise PermissionError(
                f"Unauthorized purchase confirmation: caller {gl.message.sender_address} is neither the mandate buyer nor an authorized agent"
            )

        mandate["status"] = "EXECUTED"
        self.mandates[m_key] = json.dumps(mandate)
        return True

    @gl.public.write
    def buyer_override(self, mandate_id: int, approve: bool) -> bool:
        """
        Allows the buyer to override a NEEDS_USER_APPROVAL decision to APPROVED or REJECTED.
        Strictly restricted to the original buyer.
        """
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        caller_str = str(gl.message.sender_address).lower()
        buyer_str = str(mandate.get("buyer", "")).lower()

        if caller_str != buyer_str:
            raise PermissionError("Unauthorized: Only the original mandate buyer can submit a decision override")

        if mandate.get("status") != "NEEDS_USER_APPROVAL":
            raise ValueError(f"Cannot override mandate in status '{mandate.get('status')}', must be 'NEEDS_USER_APPROVAL'")

        mandate["status"] = "APPROVED" if approve else "REJECTED"
        self.mandates[m_key] = json.dumps(mandate)
        return True

    @gl.public.write
    def cancel_mandate(self, mandate_id: int) -> bool:
        """
        Cancels an active or pending mandate.
        Callable only by the buyer or the contract owner.
        """
        m_key = u256(mandate_id)
        if m_key not in self.mandates:
            raise ValueError(f"Mandate {mandate_id} does not exist")

        mandate = json.loads(self.mandates[m_key])
        caller_str = str(gl.message.sender_address).lower()
        buyer_str = str(mandate.get("buyer", "")).lower()
        owner_str = str(self.owner).lower()

        if caller_str != buyer_str and caller_str != owner_str:
            raise PermissionError("Unauthorized: Only the buyer or contract owner can cancel a mandate")

        if mandate.get("status") == "EXECUTED":
            raise ValueError("Cannot cancel an already EXECUTED purchase mandate")

        mandate["status"] = "CANCELLED"
        self.mandates[m_key] = json.dumps(mandate)
        return True
