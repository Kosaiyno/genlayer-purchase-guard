# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json

# =============================================================================
# CONSTANTS & CANONICAL ENUMS
# =============================================================================

DECISIONS = ("APPROVED", "NEEDS_USER_APPROVAL", "REJECTED")
STOCK_STATUSES = ("IN_STOCK", "OUT_OF_STOCK")
CONDITIONS = ("NEW", "REFURBISHED", "USED")

MIN_QUOTE_CHARS = 6
MAX_QUOTE_CHARS = 120


# =============================================================================
# PURE HELPERS (no contract storage access; safe inside nondet blocks)
# =============================================================================

def _validate_address(addr_str: str) -> str:
    """Validates that a non-empty string is a valid 20-byte hex address. Empty string allowed to revoke delegation."""
    s = str(addr_str).strip()
    if not s:
        return ""
    clean_hex = s[2:] if s.startswith("0x") or s.startswith("0X") else s
    if len(clean_hex) != 40 or not all(c in "0123456789abcdefABCDEF" for c in clean_hex):
        raise ValueError(f"Invalid address format: '{addr_str}'. Must be a valid 20-byte hex address (0x...) or empty string to revoke.")
    return f"0x{clean_hex.lower()}"


def _quote_in_vendor_text(quote: str, text: str) -> bool:
    """Verifies verbatim quote grounding: 6-120 chars and appears verbatim in the fetched vendor text."""
    q = str(quote).strip()
    return MIN_QUOTE_CHARS <= len(q) <= MAX_QUOTE_CHARS and q in text


def _fetch_vendor_payload(url: str) -> dict:
    """Independently fetches vendor evidence via public web get and classifies payload."""
    try:
        resp = gl.nondet.web.get(url)
    except Exception as e:
        return {"status": "FETCH_ERROR", "text": "", "detail": str(e)[:160]}

    status_code = getattr(resp, "status", None)
    if isinstance(status_code, int) and status_code >= 400:
        return {"status": "FETCH_ERROR", "text": "", "detail": f"HTTP {status_code}"}

    body = getattr(resp, "body", resp)
    if body is None:
        raw = b""
    elif isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = str(body).encode("utf-8")

    if len(raw) == 0:
        return {"status": "EMPTY", "text": "", "detail": "0 bytes"}

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"status": "ENCODING_ERROR", "text": "", "detail": "invalid utf-8"}

    clean_text = text[:4000].strip()
    if len(clean_text) == 0:
        return {"status": "EMPTY", "text": "", "detail": "whitespace only"}

    return {"status": "OK", "text": clean_text, "detail": ""}


def _parse_vendor_judgment(raw) -> dict:
    """Parses and validates LLM judgment against strict canonical enums. Rejects UNKNOWN values."""
    try:
        if isinstance(raw, dict):
            data = raw
        else:
            s = str(raw).strip()
            start = s.find("{")
            end = s.rfind("}")
            if start < 0 or end <= start:
                return None
            data = json.loads(s[start:end + 1])

        dec = str(data.get("decision", "")).strip().upper()
        price = int(data.get("vendor_price_cents", 0))
        stock = str(data.get("stock_status", "")).strip().upper()
        cond = str(data.get("condition", "")).strip().upper()
        quote = str(data.get("verbatim_quote", "")).strip()
        rationale = str(data.get("rationale", "")).strip()[:200]
    except Exception:
        return None

    if dec not in DECISIONS:
        return None
    if stock not in STOCK_STATUSES:
        return None
    if cond not in CONDITIONS:
        return None
    if price < 0:
        return None

    return {
        "decision": dec,
        "vendor_price_cents": price,
        "stock_status": stock,
        "condition": cond,
        "verbatim_quote": quote,
        "rationale": rationale
    }


def _build_vendor_prompt(target_item: str, max_budget: int, specs: str, brand: str,
                         cond_rule: str, substitute: str, claimed_price: int, url: str, text: str) -> str:
    return (
        "ROLE: You are an impartial commercial procurement arbiter for an autonomous purchasing system.\n"
        "Your task is to independently verify vendor evidence against a buyer mandate.\n\n"
        "=== BUYER PURCHASE MANDATE ===\n"
        f"Target Item: {target_item}\n"
        f"Maximum Budget Cents: {max_budget} (${max_budget / 100:.2f} USD)\n"
        f"Required Specs: {specs}\n"
        f"Brand Rule: {brand}\n"
        f"Condition Rule: {cond_rule}\n\n"
        "=== AGENT CLAIM ===\n"
        f"Proposed Substitute: {substitute}\n"
        f"Claimed Price Cents: {claimed_price} (${claimed_price / 100:.2f} USD)\n"
        f"Vendor Evidence URL: {url}\n\n"
        "=== INDEPENDENTLY FETCHED VENDOR EVIDENCE ===\n"
        f"{text}\n\n"
        "EVALUATION DIRECTIVES:\n"
        "1. Extract the actual vendor price in cents (vendor_price_cents > 0), stock status (IN_STOCK or OUT_OF_STOCK), and condition (NEW, REFURBISHED, or USED). Never return UNKNOWN.\n"
        "2. verbatim_quote must be an exact substring (6 to 120 chars) from the vendor evidence proving price, condition, or availability.\n"
        "3. If actual vendor price > max budget, or item is OUT_OF_STOCK, or condition violates rule (e.g. REFURBISHED on NEW_ONLY), or specs are downgraded: decision must be REJECTED.\n"
        "4. If product meets/exceeds specifications and condition within budget: decision is APPROVED.\n"
        "5. If functional equivalent but deviates from preferred brand: decision is NEEDS_USER_APPROVAL.\n\n"
        "Respond with JSON only:\n"
        '{"decision": "APPROVED" | "NEEDS_USER_APPROVAL" | "REJECTED", '
        '"vendor_price_cents": <integer>, '
        '"stock_status": "IN_STOCK" | "OUT_OF_STOCK", '
        '"condition": "NEW" | "REFURBISHED" | "USED", '
        '"verbatim_quote": "<exact span from vendor text>", '
        '"rationale": "<concise explanation>"}'
    )


def _judge_vendor(prompt: str) -> dict:
    """Runs LLM prompt and parses result. Returns None if malformed."""
    try:
        raw = gl.nondet.exec_prompt(prompt, response_format="json")
    except TypeError:
        raw = gl.nondet.exec_prompt(prompt)
    except Exception:
        return None
    return _parse_vendor_judgment(raw)


# =============================================================================
# CONTRACT
# =============================================================================

class PurchaseGuard(gl.Contract):
    """
    PurchaseGuard: Autonomous On-Chain Procurement Firewall & Policy Arbiter.
    
    Protects buyers and autonomous shopping agents against:
    1. Unrelated account takeover (strict authorization: only buyer or delegated agent can propose or confirm execution).
    2. Unverified caller claims (contract independently acquires vendor evidence via gl.nondet.web.get).
    3. Hidden price surges & budget overruns (deterministic clamp against max_budget_cents).
    4. Counterfeit / downgraded specifications & refurbished goods (Leader/Validator consensus with verbatim quote grounding).
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
        Allows the buyer to explicitly authorize, update, or revoke a delegated procurement agent.
        Pass an empty string to revoke delegation. Only callable by the original mandate buyer.
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
        if len(clean_url) > 256:
            raise ValueError("Vendor evidence URL exceeds 256 character limit")
        if not clean_url.startswith("https://"):
            raise ValueError("Vendor evidence URL must use secure HTTPS protocol (https://)")
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

        # Clear stale adjudication from a prior proposal if re-proposing
        if m_key in self.adjudications:
            del self.adjudications[m_key]

        return True

    @gl.public.write
    def adjudicate_substitution(self, mandate_id: int) -> str:
        """
        Contract-Side Evidence Acquisition & Leader/Validator Equivalence Principle Adjudication:
        1. Independently fetches live vendor evidence via gl.nondet.web.get(vendor_url).
        2. Leader extracts material product facts (price, stock, condition, specs) and verbatim quote.
        3. Validator independently fetches vendor evidence from source, verifies quote in validator's own text,
           and runs independent LLM judgment requiring consensus on decision, stock status, and condition.
        4. Deterministic post-consensus safety clamps verify verbatim quotes, budget ceilings, condition rules,
           and stock availability before permitting an APPROVED state.

        PERMISSIONLESS EVALUATION DESIGN NOTE:
        Adjudication may be triggered by any caller/keeper once a proposal is submitted.
        This evaluates the immutable proposal already stored on-chain against vendor evidence.
        It does not permit an unrelated account to alter the proposal, nor can an unrelated caller
        confirm purchase execution. Final purchase confirmation remains strictly gated to the
        buyer or explicitly authorized agent via confirm_purchase().
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

        # Snapshot storage into local variables before nondet closures
        target_vendor_url = str(proposal["vendor_url"])
        target_item = str(mandate["target_item"])
        max_budget = int(mandate["max_budget_cents"])
        required_specs = str(mandate["required_specs"])
        brand_rule = str(mandate["brand_rule"])
        condition_rule = str(mandate["condition_rule"])
        substitute_name = str(proposal["substitute_item"])
        claimed_price = int(proposal["proposed_price_cents"])

        def leader_fn() -> dict:
            ev = _fetch_vendor_payload(target_vendor_url)
            if ev["status"] != "OK":
                return {
                    "status": ev["status"],
                    "decision": "REJECTED",
                    "vendor_price_cents": 0,
                    "stock_status": "OUT_OF_STOCK",
                    "condition": "USED",
                    "verbatim_quote": "NONE",
                    "rationale": f"Deterministic rejection: Vendor evidence unreachable ({ev['detail']})",
                    "fetched_text": ""
                }

            prompt = _build_vendor_prompt(target_item, max_budget, required_specs, brand_rule,
                                          condition_rule, substitute_name, claimed_price, target_vendor_url, ev["text"])
            for _ in range(2):
                judgment = _judge_vendor(prompt)
                if judgment is not None and _quote_in_vendor_text(judgment["verbatim_quote"], ev["text"]):
                    judgment["status"] = "OK"
                    judgment["fetched_text"] = ev["text"]
                    return judgment
            raise Exception("Leader could not produce a valid, verbatim-grounded vendor judgment")

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            leader = leaders_res.calldata
            if not isinstance(leader, dict):
                return False

            # 1. Independent fetch + deterministic status match
            ev = _fetch_vendor_payload(target_vendor_url)
            if str(leader.get("status", "")) != ev["status"]:
                return False
            if ev["status"] != "OK":
                return True  # fetch failure independently verified

            # 2. Structural & verbatim quote verification against validator's OWN copy of vendor evidence
            leader_j = _parse_vendor_judgment(leader)
            if leader_j is None:
                return False
            if not _quote_in_vendor_text(leader_j["verbatim_quote"], ev["text"]):
                return False

            # 3. Independent LLM judgment re-derivation: decision-bearing fields must match
            prompt = _build_vendor_prompt(target_item, max_budget, required_specs, brand_rule,
                                          condition_rule, substitute_name, claimed_price, target_vendor_url, ev["text"])
            for _ in range(2):
                mine = _judge_vendor(prompt)
                if mine is not None:
                    return (
                        mine["decision"] == leader_j["decision"] and
                        mine["stock_status"] == leader_j["stock_status"] and
                        mine["condition"] == leader_j["condition"]
                    )
            return False

        consensus_res = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

        if not isinstance(consensus_res, dict):
            raise ValueError("Malformed consensus result")

        status = str(consensus_res.get("status", ""))
        fetched_text = str(consensus_res.get("fetched_text", ""))

        if status != "OK":
            decision = "REJECTED"
            vendor_price = 0
            stock_status = "OUT_OF_STOCK"
            condition_found = "UNKNOWN"
            verbatim_quote = "NONE"
            rationale = str(consensus_res.get("rationale", "Vendor evidence fetch failed"))
        else:
            parsed = _parse_vendor_judgment(consensus_res)
            if parsed is None:
                decision = "REJECTED"
                vendor_price = 0
                stock_status = "OUT_OF_STOCK"
                condition_found = "UNKNOWN"
                verbatim_quote = "NONE"
                rationale = "Fail-closed clamp: Malformed consensus judgment format"
            else:
                decision = parsed["decision"]
                vendor_price = parsed["vendor_price_cents"]
                stock_status = parsed["stock_status"]
                condition_found = parsed["condition"]
                verbatim_quote = parsed["verbatim_quote"]
                rationale = parsed["rationale"]

                # =============================================================
                # DETERMINISTIC INVARIANT CLAMPS (Code strictly moves state)
                # =============================================================

                # Clamp 1: Verbatim Quote Grounding against actual fetched vendor payload
                if not _quote_in_vendor_text(verbatim_quote, fetched_text):
                    decision = "REJECTED"
                    rationale = "Deterministic clamp: Extracted quote does not exist verbatim in fetched vendor evidence."

                # Clamp 2: Stock Availability (Must be IN_STOCK to be approved)
                if stock_status != "IN_STOCK":
                    decision = "REJECTED"
                    rationale = f"Deterministic clamp: Vendor item is not in stock ({stock_status})."

                # Clamp 3: Condition Verification & Non-downgrade Invariant
                if condition_found not in ["NEW", "REFURBISHED", "USED"]:
                    decision = "REJECTED"
                    rationale = f"Deterministic clamp: Unknown product condition '{condition_found}'."
                elif condition_rule == "NEW_ONLY" and condition_found != "NEW":
                    decision = "REJECTED"
                    rationale = f"Deterministic clamp: Mandate requires NEW_ONLY but vendor condition is {condition_found}."

                # Clamp 4: Price & Budget Ceilings
                if vendor_price <= 0:
                    decision = "REJECTED"
                    rationale = "Deterministic clamp: Vendor price must be a valid positive amount."
                elif vendor_price > max_budget or claimed_price > max_budget:
                    decision = "REJECTED"
                    rationale = f"Deterministic clamp: Price ({max(vendor_price, claimed_price)} cents) exceeds max budget ({max_budget} cents)."

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

        NOTE ON EXECUTION SCOPE:
        confirm_purchase() records the mandate status as EXECUTED on-chain; it serves as a
        verifiable certification gate for downstream settlement systems and does not itself
        hold or transfer treasury funds directly.
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
        Updates both mandate status and adjudication record for a transparent audit trail.
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

        new_decision = "APPROVED" if approve else "REJECTED"
        mandate["status"] = new_decision
        self.mandates[m_key] = json.dumps(mandate)

        # Update adjudication record to reflect manual buyer override
        if m_key in self.adjudications:
            try:
                adj = json.loads(self.adjudications[m_key])
                adj["decision"] = new_decision
                adj["overridden_by"] = str(gl.message.sender_address)
                adj["override_rationale"] = f"Manual override by buyer to {new_decision}"
                self.adjudications[m_key] = json.dumps(adj)
            except Exception:
                pass

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
