from erp_bar.domain.action_proposal import (
    CheckpointResult,
    SupervisorProposal,
)
from erp_bar.domain.agent_context import (
    AgentContext,
)
from erp_bar.domain.decisions import (
    AgentCapability,
    AgentName,
)
from erp_bar.domain.mission import (
    MissionStatus,
)


# ==========================================================
# DOMAIN OWNERSHIP
# ==========================================================

AGENT_CAPABILITY_OWNERSHIP = {
    AgentCapability.REPORT_PROCUREMENT_FAILURE: AgentName.SALES,
    AgentCapability.INTERPRET_DEMAND: (
        AgentName.SALES
    ),

    AgentCapability.RESOLVE_PRODUCT: (
        AgentName.INVENTORY
    ),

    AgentCapability.CHECK_INVENTORY: (
        AgentName.INVENTORY
    ),

    AgentCapability.VERIFY_STOCK: (
        AgentName.INVENTORY
    ),

    AgentCapability.PROCURE_SHORTAGE: (
        AgentName.PURCHASE
    ),

    AgentCapability.CREATE_SALES_ORDER: (
        AgentName.SALES
    ),

    AgentCapability.FULFILL_DELIVERY: (
        AgentName.INVENTORY
    ),
}


def _approved(
    reason: str,
) -> CheckpointResult:
    return CheckpointResult(
        approved=True,
        reason=reason,
    )


def _rejected(
    reason: str,
) -> CheckpointResult:
    return CheckpointResult(
        approved=False,
        reason=reason,
    )


def validate_supervisor_proposal(
    context: AgentContext,
    proposal: SupervisorProposal,
) -> CheckpointResult:
    """
    Validate an autonomous Supervisor proposal.

    IMPORTANT:

    This function must NOT decide what the next
    workflow step should be.

    It only determines whether the action proposed
    by the Supervisor is:

    - owned by the selected specialist
    - grounded in verified ERP facts
    - useful for the current mission state
    - not repeating already-completed work
    - not violating process invariants
    - safe to delegate

    Invalid proposals are rejected and the rejection
    reason is returned to the Supervisor so that the
    Supervisor can replan.
    """

    mission = context.mission

    capability = proposal.capability

    agent = proposal.next_agent

    # ==========================================================
    # TERMINAL STATE
    # ==========================================================

    if mission.is_terminal():
        return _rejected(
            "The mission is already terminal. "
            "No further specialist work may be "
            "delegated."
        )

    # ==========================================================
    # AGENT OWNERSHIP
    # ==========================================================

    expected_agent = (
        AGENT_CAPABILITY_OWNERSHIP.get(
            capability
        )
    )

    if expected_agent is None:
        return _rejected(
            f"Capability {capability.value} "
            "has no registered specialist owner."
        )

    if agent != expected_agent:
        return _rejected(
            f"Capability {capability.value} belongs "
            f"to {expected_agent.value}, not "
            f"{agent.value}."
        )

    # A failed procurement cannot restart ERP fulfillment. Only the Sales
    # response remains before the mission becomes terminal.
    if capability == AgentCapability.REPORT_PROCUREMENT_FAILURE:
        if (
            mission.status != MissionStatus.PROCUREMENT_FAILED
            or not mission.procurement_failure_reason
            or not mission.procurement_failure_code
            or len(mission.requested_items) != 1
        ):
            return _rejected("Sales failure reporting requires a recorded procurement failure and one structured request.")
        return _approved("Procurement failed; Sales must prepare the customer response before the mission ends.")
    if mission.status == MissionStatus.PROCUREMENT_FAILED:
        return _rejected("Procurement has failed. Delegate the customer response to Sales; no further ERP fulfillment is permitted.")

    # ==========================================================
    # DEMAND INTERPRETATION
    # ==========================================================

    if (
        capability
        == AgentCapability.INTERPRET_DEMAND
    ):
        if mission.requested_items:
            return _rejected(
                "Customer demand has already been "
                "interpreted and structured. "
                "Repeating INTERPRET_DEMAND would "
                "not advance the mission."
            )

        return _approved(
            "The customer request has not yet been "
            "converted into structured demand."
        )

    # ==========================================================
    # EVERYTHING BELOW REQUIRES STRUCTURED DEMAND
    # ==========================================================

    if not mission.requested_items:
        return _rejected(
            "The mission does not yet contain "
            "structured requested items. A "
            "specialist operation cannot safely "
            "continue until the customer demand "
            "has been interpreted."
        )

    item = mission.requested_items[0]

    # ==========================================================
    # PRODUCT RESOLUTION
    # ==========================================================

    if (
        capability
        == AgentCapability.RESOLVE_PRODUCT
    ):
        if item.product_id is not None:
            return _rejected(
                "The requested product is already "
                f"resolved as product_id="
                f"{item.product_id}. Repeating "
                "product resolution would not "
                "advance the mission."
            )

        if mission.sales_order_id is not None:
            return _rejected(
                "Product resolution cannot be "
                "restarted after a sales order "
                "already exists."
            )

        return _approved(
            "The requested product has not yet "
            "been resolved to an Odoo product."
        )

    # ==========================================================
    # INITIAL INVENTORY CHECK
    # ==========================================================

    if (
        capability
        == AgentCapability.CHECK_INVENTORY
    ):
        # --------------------------------------------------
        # Work already completed.
        # --------------------------------------------------

        if (
            mission.status
            in {
                MissionStatus.INVENTORY_CHECKED,
                MissionStatus.STOCK_READY,
                MissionStatus
                .PROCUREMENT_REQUIRED,
                MissionStatus
                .PROCUREMENT_SENT,
                MissionStatus
                .GOODS_RECEIVED,
                MissionStatus
                .SALES_ORDER_CREATED,
                MissionStatus
                .SALES_ORDER_CONFIRMED,
                MissionStatus
                .DELIVERY_IN_PROGRESS,
                MissionStatus.DELIVERED,
            }
        ):
            return _rejected(
                "Initial inventory checking has "
                "already produced a business "
                "outcome for this mission. "
                f"Current mission status is "
                f"{mission.status.value}. "
                "Repeating CHECK_INVENTORY would "
                "not advance the mission. Replan "
                "using the current verified facts."
            )

        # RequestedItem quantities default to zero before the first
        # read. Use mission status, not those defaults, as evidence
        # that inventory has actually been checked.

        if mission.sales_order_id is not None:
            return _rejected(
                "Initial inventory checking cannot "
                "be restarted after a sales order "
                "already exists."
            )

        return _approved(
            "The mission still requires an initial "
            "product/inventory assessment."
        )

    # ==========================================================
    # STOCK VERIFICATION
    # ==========================================================

    if (
        capability
        == AgentCapability.VERIFY_STOCK
    ):
        if item.product_id is None:
            return _rejected(
                "Stock verification requires a "
                "verified product_id."
            )

        if mission.status == MissionStatus.PROCUREMENT_REQUIRED:
            return _rejected(
                "Inventory has already established the shortage and no "
                "intervening stock-changing mission action is recorded. "
                "The stored assessment is usable evidence for procurement. "
                "Repeating VERIFY_STOCK would not advance the mission. "
                "Stock must be verified again after goods are received."
            )

        # Independent verification is useful after
        # procurement/receipt, but it should not loop
        # indefinitely after stock readiness has already
        # been established.

        if (
            mission.status
            == MissionStatus.STOCK_READY
            and item.shortage_qty <= 0
        ):
            return _rejected(
                "Stock has already been independently "
                "verified as sufficient and the "
                "mission is STOCK_READY. Repeating "
                "VERIFY_STOCK would not advance "
                "the mission."
            )

        if mission.status in {
            MissionStatus.SALES_ORDER_CREATED,
            MissionStatus.SALES_ORDER_CONFIRMED,
            MissionStatus.DELIVERY_IN_PROGRESS,
        }:
            return _rejected(
                "Stock verification has already "
                "been completed and the mission "
                "has progressed beyond stock "
                "readiness."
            )

        return _approved(
            "The product is resolved and fresh "
            "Odoo stock verification is a valid "
            "operation."
        )

    # ==========================================================
    # PROCUREMENT
    # ==========================================================

    if (
        capability
        == AgentCapability.PROCURE_SHORTAGE
    ):
        if item.product_id is None:
            return _rejected(
                "Procurement cannot begin because "
                "the requested product has not been "
                "resolved."
            )

        if item.shortage_qty <= 0:
            return _rejected(
                "Procurement is not justified "
                "because there is no verified "
                "positive stock shortage."
            )

        if mission.sales_order_id is not None:
            return _rejected(
                "A new procurement process cannot "
                "be started after a customer sales "
                "order already exists in this V1 "
                "mission."
            )

        if mission.status in {
            MissionStatus.PROCUREMENT_SENT,
            MissionStatus.GOODS_RECEIVED,
        }:
            return _rejected(
                "Procurement has already progressed "
                f"to {mission.status.value}. "
                "Starting PROCURE_SHORTAGE again "
                "could duplicate purchasing."
            )

        return _approved(
            "A positive verified shortage exists "
            "and Purchase owns the procurement "
            "objective."
        )

    # ==========================================================
    # SALES ORDER
    # ==========================================================

    if (
        capability
        == AgentCapability.CREATE_SALES_ORDER
    ):
        if item.product_id is None:
            return _rejected(
                "A sales order cannot be created "
                "without a verified product_id."
            )

        if item.shortage_qty > 0:
            return _rejected(
                "A sales order cannot be created "
                "while a verified inventory "
                f"shortage of {item.shortage_qty} "
                "still exists."
            )

        if mission.status not in {
            MissionStatus.STOCK_READY,
            MissionStatus.SALES_ORDER_CREATED,
        }:
            return _rejected(
                "Sales-order processing requires "
                "verified stock readiness. "
                f"Current mission status is "
                f"{mission.status.value}."
            )

        if (
            mission.status
            == MissionStatus.STOCK_READY
            and mission.sales_order_id
            is not None
        ):
            return _rejected(
                "Mission state is inconsistent: "
                "a sales_order_id already exists "
                "while status is STOCK_READY."
            )

        return _approved(
            "Verified inventory can fulfill the "
            "customer quantity and Sales may "
            "create or resume the customer order."
        )

    # ==========================================================
    # DELIVERY
    # ==========================================================

    if (
        capability
        == AgentCapability.FULFILL_DELIVERY
    ):
        if mission.sales_order_id is None:
            return _rejected(
                "Delivery cannot begin because "
                "there is no verified sales_order_id."
            )

        if mission.status not in {
            MissionStatus.SALES_ORDER_CONFIRMED,
            MissionStatus.DELIVERY_IN_PROGRESS,
        }:
            return _rejected(
                "Delivery requires a confirmed "
                "sales order. "
                f"Current mission status is "
                f"{mission.status.value}."
            )

        return _approved(
            "A confirmed customer sales order "
            "exists and Inventory may perform "
            "warehouse delivery fulfillment."
        )

    # ==========================================================
    # FALLBACK
    # ==========================================================

    return _rejected(
        "The proposed delegation could not be "
        "validated against the current mission "
        "state and verified ERP facts."
    )
