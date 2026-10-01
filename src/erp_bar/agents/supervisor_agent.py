from erp_bar.runtime.model_json import parse_model_object
from erp_bar.runtime.events import observe_step, emit, clean_text

import json

from erp_bar.domain.action_proposal import (
    SupervisorProposal,
)
from erp_bar.domain.agent_context import (
    AgentContext,
)
from erp_bar.domain.decisions import (
    AgentCapability,
    AgentName,
    DecisionType,
    SupervisorDecision,
)
from erp_bar.domain.mission import MissionStatus
from erp_bar.llm import invoke_llm
from erp_bar.runtime.supervisor_checkpoint import (
    AGENT_CAPABILITY_OWNERSHIP,
    validate_supervisor_proposal,
)


SYSTEM_PROMPT = """
You are the autonomous Supervisor Agent for ERP_BAR.
Choose the specialist business capability that advances the customer mission
toward DELIVERED. Specialists choose their tool actions; Python executes them.
Stop at delivery; invoices and payments are outside this mission.

STATE AND EVIDENCE
- Read the actual mission snapshot before choosing. Customer request text is
  not structured demand. structured_demand_present tells you whether Sales
  has interpreted it; NEW alone does not tell you this.
- inventory_observation explains whether requested_items stock quantities
  are usable. Null quantities mean unknown, never zero stock or stock ready.
- GOODS_RECEIVED confirms procurement receipt, not current available stock.
  Quantities marked OUTDATED_AFTER_PROCUREMENT describe the earlier stock
  assessment. They establish neither a remaining shortage nor readiness.
  Obtain independent stock verification before proposing Sales processing.
- LAST_VERIFIED is usable evidence for the next business decision when
  usable_for_next_decision is true. Being a stored observation does NOT make
  it outdated. No intervening stock-changing mission action is recorded.
  In PROCUREMENT_REQUIRED, the verified shortage justifies procurement;
  do not repeat VERIFY_STOCK solely because the observation is a snapshot.
  After receipt, OUTDATED_AFTER_PROCUREMENT explicitly requires verification.
  Sales still rechecks stock before committing an order.
- After sales confirmation, quantities marked BEFORE_SALES_CONFIRMATION are
  historical: confirmation may have reserved stock for this order. Do not
  claim they describe current free stock or use them to justify delivery.
  Historical stock quantities and previous free-text explanations are omitted
  at this stage. Requested quantity describes demand, not current availability.
  Justify FULFILL_DELIVERY using the confirmed sales order and recorded delivery
  status only. Do not claim a numeric stock quantity is currently available.
  The delivery skill checks the actual picking and reservations.
- A null delivery_picking_id means NOT_RECORDED in the mission. It does not
  prove that no Odoo picking exists. Describe locating and fulfilling the
  order's delivery, not creating a missing picking without evidence.
- Previous specialist results are evidence from their stage, not automatically
  current warehouse facts. Do not invent facts in your objective or reason.
- PROCUREMENT_FAILED is pending a customer response, not another procurement
  attempt. Delegate REPORT_PROCUREMENT_FAILURE to Sales. Preserve recorded
  ERP IDs; failure does not undo existing purchases or receipts.

CAPABILITIES
- sales_agent / REPORT_PROCUREMENT_FAILURE: prepare a customer-facing inability
  to complete the order from the recorded procurement failure, then end FAILED.
- sales_agent / INTERPRET_DEMAND: interpret the customer request when structured
  requested items are absent.
- inventory_agent / CHECK_INVENTORY: resolve the product and assess initial
  warehouse availability.
- inventory_agent / RESOLVE_PRODUCT: the existing Inventory capability for an
  unresolved product; it also performs the initial inventory assessment.
- inventory_agent / VERIFY_STOCK: independently read warehouse availability
  after stock changes, especially procurement receipt.
- purchase_agent / PROCURE_SHORTAGE: resolve a verified shortage. Purchase
  chooses supplier and PO/receipt tool actions from verified results.
- sales_agent / CREATE_SALES_ORDER: create or resume and confirm the customer
  order after stock readiness has been verified.
- inventory_agent / FULFILL_DELIVERY: locate, reserve and validate delivery for
  a confirmed sales order using the existing delivery business skill.

DECISION RULES
Choose only an agent/capability pair in permitted_capabilities. This list is
computed by the same Python checkpoint that validates your proposal. It is a
set of permitted choices, not an instruction to choose the first entry.
Choose the useful capability based on the mission evidence. Do not repeat work
that is already complete. When rejected, use the feedback to correct your
proposal. Python will validate the selected action again before delegation.

OUTPUT
Return only one JSON object with these four nonempty string fields:
next_agent: the exact owner from the chosen permitted entry.
capability: the exact capability from that entry.
objective: the business outcome to obtain through this delegation.
reason: why the actual mission evidence supports this action now; distinguish
observed facts, historical observations and unknown information.
Do not return markdown or additional text.
"""


def _extract_json(text: str) -> dict:
    return parse_model_object(text)


def _parse_proposal(
    response: str,
) -> SupervisorProposal:
    """
    Parse loose LLM JSON and construct the internal
    Pydantic proposal in Python.

    We intentionally do NOT use
    with_structured_output().
    """

    data = _extract_json(
        response
    )

    next_agent_raw = data.get(
        "next_agent"
    )

    capability_raw = data.get(
        "capability"
    )

    objective = data.get(
        "objective"
    )

    reason = data.get(
        "reason"
    )

    if not next_agent_raw:
        raise ValueError(
            "Supervisor proposal is missing "
            "next_agent."
        )

    if not capability_raw:
        raise ValueError(
            "Supervisor proposal is missing "
            "capability."
        )

    if not objective:
        raise ValueError(
            "Supervisor proposal is missing "
            "objective."
        )

    if not reason:
        raise ValueError(
            "Supervisor proposal is missing "
            "reason."
        )

    try:
        next_agent = AgentName(
            str(next_agent_raw)
        )

    except ValueError as exc:
        raise ValueError(
            "Supervisor proposed unknown agent: "
            f"{next_agent_raw!r}"
        ) from exc

    try:
        capability = AgentCapability(
            str(
                capability_raw
            ).upper()
        )

    except ValueError as exc:
        raise ValueError(
            "Supervisor proposed unknown "
            "capability: "
            f"{capability_raw!r}"
        ) from exc

    return SupervisorProposal(
        next_agent=next_agent,
        capability=capability,
        objective=str(
            objective
        ).strip(),
        reason=str(
            reason
        ).strip(),
    )


def _permitted_capabilities(context: AgentContext) -> list[dict]:
    """Expose existing validation results without selecting or executing work."""
    permitted = []
    for capability, owner in AGENT_CAPABILITY_OWNERSHIP.items():
        candidate = SupervisorProposal(
            next_agent=owner,
            capability=capability,
            objective="Assess whether this capability is permitted.",
            reason="Inspect the existing mission checkpoint without executing work.",
        )
        result = validate_supervisor_proposal(context=context, proposal=candidate)
        if result.approved:
            permitted.append({
                "next_agent": owner.value,
                "capability": capability.value,
                "precondition": result.reason,
            })
    return permitted


def _mission_snapshot(context: AgentContext) -> dict:
    mission = context.mission
    # These labels describe stored observations; building a prompt never reads
    # Odoo, changes mission quantities, or makes an observation current.
    if mission.status in {MissionStatus.NEW, MissionStatus.PRODUCT_RESOLVED}:
        observation = "NOT_CHECKED"
        meaning = "Default quantities are not stock evidence. Availability and shortage are unknown."
    elif mission.status in {MissionStatus.PROCUREMENT_SENT, MissionStatus.GOODS_RECEIVED}:
        observation = "OUTDATED_AFTER_PROCUREMENT"
        meaning = "Stored quantities predate procurement. Current availability and shortage require verification."
    elif mission.status in {
        MissionStatus.SALES_ORDER_CONFIRMED,
        MissionStatus.DELIVERY_IN_PROGRESS,
        MissionStatus.DELIVERED,
    }:
        observation = "BEFORE_SALES_CONFIRMATION"
        meaning = "Stored quantities predate confirmation/reservation and possibly delivery; current free stock is unknown."
    elif mission.status in {
        MissionStatus.INVENTORY_CHECKED, MissionStatus.PROCUREMENT_REQUIRED,
        MissionStatus.STOCK_READY, MissionStatus.SALES_ORDER_CREATED,
    }:
        observation = "LAST_VERIFIED"
        meaning = "Verified assessment usable for the next business decision; no intervening stock-changing mission action is recorded. A snapshot is not outdated merely because it is stored."
    else:
        observation = "UNKNOWN"
        meaning = "No usable stock assessment can be established from this mission stage."

    items = [item.model_dump(mode="json") for item in mission.requested_items]
    if observation in {"NOT_CHECKED", "UNKNOWN", "BEFORE_SALES_CONFIRMATION"}:
        for item in items:
            item["available_qty"] = None
            item["shortage_qty"] = None

    previous_result = (
        context.previous_decision.model_dump(mode="json")
        if context.previous_decision else None
    )
    if observation == "BEFORE_SALES_CONFIRMATION" and previous_result:
        # The Sales reason/facts can repeat its pre-confirmation availability.
        # Pass only the recorded outcome/identities to the delivery delegation.
        previous_result = {
            "agent": previous_result["agent"],
            "decision": previous_result["decision"],
            "facts": {
                key: value for key, value in previous_result["facts"].items()
                if key in {"sales_order_id", "sales_order_state", "state",
                           "product_id", "customer_id", "picking_id"}
            },
        }

    return {
        "mission_id": mission.mission_id,
        "customer_request": mission.customer_request,
        "customer_id": mission.customer_id,
        "status": mission.status.value,
        "structured_demand_present": bool(mission.requested_items),
        "requested_items": items,
        "inventory_observation": {
            "status": observation,
            "meaning": meaning,
            "usable_for_next_decision": observation == "LAST_VERIFIED",
        },
        "supplier_id": mission.supplier_id,
        "purchase_order_ids": mission.purchase_order_ids,
        "sales_order_id": mission.sales_order_id,
        "delivery_picking_id": mission.delivery_picking_id,
        "delivery_record_knowledge": (
            "ID_RECORDED" if mission.delivery_picking_id is not None else "NOT_RECORDED"
        ),
        "errors": mission.errors,
        "procurement_failure_reason": mission.procurement_failure_reason,
        "procurement_failure_code": mission.procurement_failure_code,
        "customer_message": mission.customer_message,
        "previous_specialist_result": previous_result,
        "permitted_capabilities": _permitted_capabilities(context),
    }


def decide_next_agent(
    context: AgentContext,
) -> SupervisorDecision:
    """
    Autonomous Supervisor loop.

    The LLM chooses the process step.

    Deterministic Python only validates whether the
    proposed delegation is legal.

    If rejected, the rejection reason is fed back to
    the Supervisor and it must replan.
    """

    mission = context.mission

    if mission.is_terminal():
        raise ValueError(
            "Supervisor cannot delegate work for "
            f"terminal mission {mission.status.value}."
        )

    snapshot = _mission_snapshot(
        context
    )

    checkpoint_feedback: list[str] = []

    max_attempts = 5

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        prompt = f"""
MISSION STATE
=============

{json.dumps(snapshot, ensure_ascii=False, indent=2)}


PREVIOUS CHECKPOINT REJECTIONS
==============================

{json.dumps(checkpoint_feedback, ensure_ascii=False)}


Decide which specialist should act next.

Return only the required JSON proposal.
"""

        response = invoke_llm(
            SYSTEM_PROMPT,
            prompt,
        )

        print()
        print(
            "[supervisor] Autonomous proposal attempt:",
            attempt,
        )

        print(
            "[supervisor] Raw proposal:",
            response,
        )

        try:
            proposal = _parse_proposal(
                response
            )

        except Exception as exc:
            feedback = (
                "Proposal parsing failed: "
                f"{exc}"
            )

            checkpoint_feedback.append(
                feedback
            )
            observe_step({"approved": False, "feedback": feedback})

            print(
                "[supervisor] Rejected:",
                feedback,
            )

            continue

        print(
            "[supervisor] Proposed agent:",
            proposal.next_agent.value,
        )

        print(
            "[supervisor] Proposed capability:",
            proposal.capability.value,
        )

        print(
            "[supervisor] Proposed objective:",
            proposal.objective,
        )

        checkpoint = (
            validate_supervisor_proposal(
                context=context,
                proposal=proposal,
            )
        )

        if not checkpoint.approved:
            feedback = (
                f"Rejected {proposal.next_agent.value}/{proposal.capability.value}: "
                f"{checkpoint.reason}"
            )

            checkpoint_feedback.append(
                feedback
            )
            observe_step({"approved": False, "feedback": feedback})

            print(
                "[supervisor] Checkpoint rejected:",
                checkpoint.reason,
            )

            continue

        print(
            "[supervisor] Checkpoint approved:",
            checkpoint.reason,
        )

        emit("instruction", target=proposal.next_agent.value,
             action=proposal.capability.value,
             objective=clean_text(proposal.objective),
             message=clean_text(proposal.reason), validated=True)

        return SupervisorDecision(
            decision=DecisionType.DELEGATE,
            reason=(
                f"{proposal.reason} "
                f"Checkpoint: "
                f"{checkpoint.reason}"
            ),
            requested_capability=(
                proposal.capability
            ),
            customer_message=None,
        )

    raise RuntimeError(
        "Autonomous Supervisor could not produce "
        "an approved delegation after "
        f"{max_attempts} attempts. "
        f"Checkpoint feedback: "
        f"{checkpoint_feedback}"
    )
