"""Step 1 regressions. These tests never connect to Odoo or an LLM."""

import unittest
from unittest.mock import Mock, patch

from erp_bar.domain.action_proposal import SupervisorProposal
from erp_bar.domain.agent_context import AgentContext
from erp_bar.domain.mission import MissionStatus, OrderMission, RequestedItem
from erp_bar.odoo.bridge import OdooBridge
from erp_bar.runtime.supervisor_checkpoint import validate_supervisor_proposal
from erp_bar.skills import erp_skills
from erp_bar.tools import delivery_tools, inventory_tools
from erp_bar.tools.delivery_schemas import (
    DeliveryRecord,
    GetDeliveryResult,
    ValidateDeliveryInput,
)
from erp_bar.tools.inventory_schemas import GetAvailableStockInput


def delivery(state="assigned", quantity=5.0, reserved=5.0, delivered=0.0):
    return {
        "picking_id": 101,
        "name": "WH/OUT/00101",
        "sales_order_id": 201,
        "customer_id": 17,
        "product_id": 15,
        "quantity": quantity,
        "state": state,
        "reserved_qty": reserved,
        "delivered_qty": delivered,
    }


def delivery_bridge(record):
    bridge = object.__new__(OdooBridge)
    bridge.warehouse_id = 1
    bridge._read_delivery = Mock(return_value=record)
    bridge.execute = Mock(return_value=True)
    bridge._set_picking_done_quantities = Mock()
    return bridge


class WarehouseStockTests(unittest.TestCase):
    def make_bridge(self, physical=5.0, reserved=3.0):
        bridge = object.__new__(OdooBridge)
        bridge.warehouse_id = 1

        def execute(model, method, *args, **kwargs):
            if (model, method) == ("product.product", "read"):
                return [{"display_name": "Lemonade", "qty_available": 100, "free_qty": 90}]
            if (model, method) == ("stock.warehouse", "read"):
                self.assertEqual(args[0], [1])
                return [{"name": "Warehouse", "code": "WH", "lot_stock_id": [8, "WH/Stock"]}]
            if (model, method) == ("stock.quant", "search_read"):
                self.assertIn(["product_id", "=", 15], args[0])
                self.assertIn(["location_id", "child_of", 8], args[0])
                self.assertIn(["location_id.usage", "=", "internal"], args[0])
                return [{"location_id": [8, "WH/Stock"], "quantity": physical, "reserved_quantity": reserved}]
            self.fail(f"Unexpected RPC: {model}.{method}")

        bridge.execute = Mock(side_effect=execute)
        return bridge

    def test_bridge_uses_warehouse_free_stock_instead_of_global_physical_stock(self):
        self.assertEqual(self.make_bridge().get_available_stock(15), 2.0)

    def test_new_orders_cannot_use_reserved_stock(self):
        self.assertEqual(self.make_bridge(physical=1, reserved=1).get_available_stock(15), 0.0)

    def test_negative_free_stock_is_clamped_to_zero(self):
        self.assertEqual(self.make_bridge(physical=1, reserved=2).get_available_stock(15), 0.0)

    def test_inventory_tool_and_bridge_report_the_same_stock(self):
        bridge = self.make_bridge()
        with patch("erp_bar.odoo.inventory_service.get_odoo_bridge", return_value=bridge):
            result = inventory_tools.get_available_stock(GetAvailableStockInput(product_id=15))
        self.assertTrue(result.ok)
        self.assertEqual(result.available_qty, bridge.get_available_stock(15))


class DeliveryStockTests(unittest.TestCase):
    def test_stock_reserved_for_this_delivery_is_still_available_to_it(self):
        bridge = delivery_bridge(delivery())
        bridge.get_available_stock = Mock(return_value=0.0)
        result = bridge.check_delivery_availability(101)
        self.assertTrue(result["can_fulfill"])
        self.assertEqual(result["available_qty"], 5.0)

    def test_partial_own_reservation_combines_with_remaining_free_stock(self):
        bridge = delivery_bridge(delivery(state="confirmed", reserved=2.0))
        bridge.get_available_stock = Mock(return_value=3.0)
        result = bridge.check_delivery_availability(101)
        self.assertTrue(result["can_fulfill"])
        self.assertEqual(result["available_qty"], 5.0)

    def test_stock_reserved_for_other_orders_is_not_available(self):
        bridge = delivery_bridge(delivery(state="confirmed", reserved=0.0))
        bridge.get_available_stock = Mock(return_value=0.0)
        self.assertFalse(bridge.check_delivery_availability(101)["can_fulfill"])

    def test_read_delivery_does_not_invent_a_full_reservation_from_state(self):
        bridge = object.__new__(OdooBridge)
        bridge.execute = Mock(side_effect=[
            [{"name": "WH/OUT/00101", "state": "assigned", "sale_id": [201, "SO201"], "partner_id": [17, "Customer"]}],
            [301],
            [{"product_id": [15, "Lemonade"], "product_uom_qty": 5.0, "quantity": 2.0}],
        ])
        result = bridge._read_delivery(101)
        self.assertEqual(result["reserved_qty"], 2.0)
        self.assertEqual(result["delivered_qty"], 0.0)

    def test_failed_reservation_does_not_set_quantities_or_validate(self):
        bridge = delivery_bridge(delivery(state="confirmed", reserved=0.0))
        with self.assertRaisesRegex(RuntimeError, "reserv"):
            bridge.validate_delivery(101)
        bridge._set_picking_done_quantities.assert_not_called()
        self.assertNotIn("button_validate", [call.args[1] for call in bridge.execute.call_args_list])

    def test_assigned_but_under_reserved_delivery_is_blocked(self):
        bridge = delivery_bridge(delivery(reserved=2.0))
        with self.assertRaisesRegex(RuntimeError, "reserv"):
            bridge.validate_delivery(101)
        bridge._set_picking_done_quantities.assert_not_called()
        bridge.execute.assert_not_called()

    def test_cancelled_delivery_is_not_mutated(self):
        bridge = delivery_bridge(delivery(state="cancel", reserved=0.0))
        with self.assertRaisesRegex(ValueError, "cancel"):
            bridge.validate_delivery(101)
        bridge.execute.assert_not_called()
        bridge._set_picking_done_quantities.assert_not_called()

    def test_successful_reservation_is_read_back_before_validation(self):
        bridge = delivery_bridge(delivery())
        bridge._read_delivery.side_effect = [
            delivery(state="confirmed", reserved=0.0),
            delivery(state="assigned"),
            delivery(state="done", reserved=0.0, delivered=5.0),
        ]
        result = bridge.validate_delivery(101)
        self.assertEqual(result["state"], "done")
        self.assertEqual(result["delivered_qty"], 5.0)
        self.assertEqual(bridge._read_delivery.call_count, 3)
        self.assertEqual([call.args[1] for call in bridge.execute.call_args_list], ["action_assign", "button_validate"])

    def test_completed_delivery_is_safe_to_retry(self):
        bridge = delivery_bridge(delivery(state="done", reserved=0.0, delivered=5.0))
        result = bridge.validate_delivery(101)
        self.assertEqual(result["delivered_qty"], 5.0)
        bridge.execute.assert_not_called()
        bridge._set_picking_done_quantities.assert_not_called()

    def test_partial_completed_delivery_is_not_tool_success(self):
        bridge = Mock()
        bridge.validate_delivery.return_value = delivery(state="done", reserved=0.0, delivered=2.0)
        with patch.object(delivery_tools, "get_odoo_bridge", return_value=bridge):
            result = delivery_tools.validate_delivery(ValidateDeliveryInput(picking_id=101))
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "DELIVERY_QUANTITY_INCOMPLETE")

    def test_partial_completed_delivery_is_not_skill_success_on_retry(self):
        result = GetDeliveryResult(ok=True, delivery=DeliveryRecord(**delivery(state="done", reserved=0.0, delivered=2.0)))
        with patch.object(erp_skills, "get_delivery", return_value=result), patch.object(erp_skills, "validate_delivery") as validate:
            outcome = erp_skills.fulfill_delivery(201)
        self.assertFalse(outcome["ok"])
        validate.assert_not_called()


class InventoryCheckpointTests(unittest.TestCase):
    def check(self, status, *, product_id=15, available=0.0, shortage=0.0):
        mission = OrderMission(
            customer_request="I want 5 Lemonade",
            requested_items=[RequestedItem(product_query="Lemonade", product_id=product_id, requested_qty=5, available_qty=available, shortage_qty=shortage)],
            status=status,
        )
        proposal = SupervisorProposal(next_agent="inventory_agent", capability="CHECK_INVENTORY", objective="Read stock", reason="Need verified inventory facts")
        return validate_supervisor_proposal(AgentContext(mission=mission), proposal)

    def test_default_zero_quantities_do_not_mean_stock_was_checked(self):
        self.assertTrue(self.check(MissionStatus.PRODUCT_RESOLVED).approved)

    def test_new_demand_can_be_checked(self):
        self.assertTrue(self.check(MissionStatus.NEW, product_id=None).approved)

    def test_verified_zero_stock_is_not_treated_as_unread(self):
        self.assertFalse(self.check(MissionStatus.INVENTORY_CHECKED, shortage=5).approved)

    def test_stock_ready_does_not_repeat_initial_check(self):
        self.assertFalse(self.check(MissionStatus.STOCK_READY, available=5).approved)


if __name__ == "__main__":
    unittest.main()
