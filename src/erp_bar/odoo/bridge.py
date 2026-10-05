import os
import xmlrpc.client
from typing import Any

from dotenv import load_dotenv


load_dotenv()


def _rpc_transport(url, timeout):
    if timeout is None:
        return None
    base = xmlrpc.client.SafeTransport if url.startswith('https:') else xmlrpc.client.Transport
    class BoundedTransport(base):
        def make_connection(self, host):
            connection = super().make_connection(host)
            connection.timeout = timeout
            return connection
    return BoundedTransport()


def _required_env(
    name: str,
) -> str:
    value = os.getenv(name)

    if value is None or not value.strip():
        raise RuntimeError(
            f"Missing required environment variable: {name}"
        )

    return value.strip()


def _required_int_env(
    name: str,
) -> int:
    value = _required_env(name)

    try:
        return int(value)

    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be an integer."
        ) from exc


class OdooBridge:
    """
    Real ERP_BAR Odoo XML-RPC backend.

    Agents never receive this object directly.

    Only controlled ERP_BAR tool functions may
    call these methods.
    """

    def __init__(
        self,
        rpc_timeout=None,
    ):
        self.url = _required_env(
            "ODOO_URL"
        ).rstrip("/")

        self.db = _required_env(
            "ODOO_DB"
        )

        self.username = _required_env(
            "ODOO_USER"
        )

        self.password = _required_env(
            "ODOO_PASSWORD"
        )

        self.walk_in_customer_id = (
            _required_int_env(
                "ODOO_WALK_IN_CUSTOMER_ID"
            )
        )

        self.warehouse_id = (
            _required_int_env(
                "ODOO_WAREHOUSE_ID"
            )
        )

        self.common = (
            xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/common", transport=_rpc_transport(self.url, rpc_timeout)
            )
        )

        try:
            self.uid = (
                self.common.authenticate(
                    self.db,
                    self.username,
                    self.password,
                    {},
                )
            )

        except Exception as exc:
            raise ConnectionError(
                "Odoo XML-RPC authentication "
                f"failed: {exc}"
            ) from exc

        if not self.uid:
            raise PermissionError(
                "Odoo authentication failed."
            )

        self.models = (
            xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/object", transport=_rpc_transport(self.url, rpc_timeout)
            )
        )

    # ==========================================================
    # BASE RPC
    # ==========================================================

    def execute(
        self,
        model: str,
        method: str,
        *args,
        **kwargs,
    ):
        return self.models.execute_kw(
            self.db,
            self.uid,
            self.password,
            model,
            method,
            list(args),
            kwargs if kwargs else {},
        )

    # ==========================================================
    # CONFIGURATION
    # ==========================================================

    def validate_runtime_configuration(
        self,
    ) -> dict[str, Any]:
        customer = self.execute(
            "res.partner",
            "read",
            [self.walk_in_customer_id],
            fields=["name"],
        )

        if not customer:
            raise ValueError(
                "Configured walk-in customer "
                f"#{self.walk_in_customer_id} "
                "does not exist."
            )

        warehouse = self.execute(
            "stock.warehouse",
            "read",
            [self.warehouse_id],
            fields=[
                "name",
                "code",
                "in_type_id",
                "out_type_id",
            ],
        )

        if not warehouse:
            raise ValueError(
                "Configured warehouse "
                f"#{self.warehouse_id} "
                "does not exist."
            )

        return {
            "uid": self.uid,
            "customer_id": (
                self.walk_in_customer_id
            ),
            "customer_name": (
                customer[0]["name"]
            ),
            "warehouse_id": (
                self.warehouse_id
            ),
            "warehouse_name": (
                warehouse[0]["name"]
            ),
            "warehouse_code": (
                warehouse[0].get("code")
            ),
        }

    # ==========================================================
    # PRODUCT
    # ==========================================================

    def get_variant_id(
        self,
        product_template_id: int,
    ) -> int:
        """
        Resolve product.template to product.product.

        This follows the same pattern as your
        previously tested connector.
        """

        variant_ids = self.execute(
            "product.product",
            "search",
            [
                [
                    "product_tmpl_id",
                    "=",
                    product_template_id,
                ]
            ],
            limit=1,
        )

        if not variant_ids:
            raise ValueError(
                "No product.product variant found "
                "for product.template "
                f"#{product_template_id}."
            )

        return int(
            variant_ids[0]
        )

    def _read_product(
        self,
        product_id: int,
    ) -> dict[str, Any] | None:
        records = self.execute(
            "product.product",
            "read",
            [product_id],
            fields=[
                "display_name",
                "name",
                "default_code",
                "barcode",
                "product_tmpl_id",
            ],
        )

        if not records:
            return None

        record = records[0]

        template = record.get(
            "product_tmpl_id"
        )

        return {
            "product_id": int(
                record["id"]
            ),
            "name": (
                record.get("display_name")
                or record.get("name")
                or str(record["id"])
            ),
            "sku": (
                record.get("default_code")
                or None
            ),
            "barcode": (
                record.get("barcode")
                or None
            ),
            "product_template_id": (
                int(template[0])
                if template
                else None
            ),
        }

    def search_product(
        self,
        query: str,
    ) -> dict[str, Any] | None:
        """
        Resolve customer product text to
        product.product.

        Search priority:
        1. exact SKU
        2. exact barcode
        3. exact-ish name
        4. name contains query
        """

        query = query.strip()

        if not query:
            return None

        # --------------------------------------------------
        # EXACT SKU
        # --------------------------------------------------

        ids = self.execute(
            "product.product",
            "search",
            [
                [
                    "default_code",
                    "=",
                    query,
                ]
            ],
            limit=1,
        )

        if ids:
            return self._read_product(
                int(ids[0])
            )

        # --------------------------------------------------
        # EXACT BARCODE
        # --------------------------------------------------

        ids = self.execute(
            "product.product",
            "search",
            [
                [
                    "barcode",
                    "=",
                    query,
                ]
            ],
            limit=1,
        )

        if ids:
            return self._read_product(
                int(ids[0])
            )

        # --------------------------------------------------
        # NAME
        # --------------------------------------------------

        ids = self.execute(
            "product.product",
            "search",
            [
                [
                    "name",
                    "=ilike",
                    query,
                ]
            ],
            limit=1,
        )

        if ids:
            return self._read_product(
                int(ids[0])
            )

        # --------------------------------------------------
        # NAME CONTAINS
        # --------------------------------------------------

        ids = self.execute(
            "product.product",
            "search",
            [
                [
                    "name",
                    "ilike",
                    query,
                ]
            ],
            limit=1,
        )

        if not ids:
            return None

        return self._read_product(
            int(ids[0])
        )

    def create_product(
        self,
        name: str,
        sku: str | None = None,
    ) -> dict[str, Any]:
        """
        Idempotent product creation.

        Search first so a mission retry does not
        create another product.
        """

        existing = self.search_product(
            sku or name
        )

        if existing is not None:
            return {
                **existing,
                "created": False,
            }

        template_values = {
            "name": name,
            "sale_ok": True,
            "purchase_ok": True,
        }

        template_id = self.execute(
            "product.template",
            "create",
            [template_values],
        )

        if isinstance(
            template_id,
            list,
        ):
            template_id = (
                template_id[0]
            )

        variant_ids = self.execute(
            "product.product",
            "search",
            [
                [
                    "product_tmpl_id",
                    "=",
                    template_id,
                ]
            ],
            limit=1,
        )

        if not variant_ids:
            raise RuntimeError(
                "Odoo created product.template "
                "but no product.product variant "
                "was generated."
            )

        product_id = int(
            variant_ids[0]
        )

        if sku:
            self.execute(
                "product.product",
                "write",
                [product_id],
                {
                    "default_code": sku,
                },
            )

        product = self._read_product(
            product_id
        )

        if product is None:
            raise RuntimeError(
                "Created product could not "
                "be read back from Odoo."
            )

        return {
            **product,
            "created": True,
        }

    # ==========================================================
    # INVENTORY
    # ==========================================================

    def get_available_stock(
        self,
        product_id: int,
    ) -> float:
        """Free stock in this bridge's configured warehouse."""
        from erp_bar.odoo.inventory_service import (
            get_warehouse_stock_snapshot,
        )

        snapshot = get_warehouse_stock_snapshot(
            product_id=product_id,
            warehouse_id=self.warehouse_id,
            bridge=self,
        )
        return float(snapshot["available_qty"])

    # ==========================================================
    # VENDORS
    # ==========================================================

    def get_product_vendors(
        self,
        product_id: int,
    ) -> list[dict[str, Any]]:
        product_data = self.execute(
            "product.product",
            "read",
            [product_id],
            fields=[
                "display_name",
                "seller_ids",
            ],
        )

        if not product_data:
            return []

        seller_ids = (
            product_data[0].get(
                "seller_ids",
                [],
            )
        )

        if not seller_ids:
            return []

        supplier_records = self.execute(
            "product.supplierinfo",
            "read",
            seller_ids,
            fields=[
                "partner_id",
                "price",
                "min_qty",
                "product_id",
            ],
        )

        vendors = []

        for supplier in supplier_records:
            variant = supplier.get("product_id")
            if variant and int(variant[0]) != product_id:
                continue
            partner = supplier.get(
                "partner_id"
            )

            if not partner:
                continue

            vendors.append(
                {
                    "vendor_id": int(
                        partner[0]
                    ),
                    "name": str(
                        partner[1]
                    ),
                    "price": float(
                        supplier.get(
                            "price",
                            0,
                        )
                        or 0
                    ),
                    "min_qty": float(
                        supplier.get(
                            "min_qty",
                            0,
                        )
                        or 0
                    ),
                }
            )

        return vendors

    # ==========================================================
    # WAREHOUSE
    # ==========================================================

    def _warehouse_in_type_id(
        self,
    ) -> int:
        data = self.execute(
            "stock.warehouse",
            "read",
            [self.warehouse_id],
            fields=[
                "in_type_id",
            ],
        )

        if not data:
            raise ValueError(
                "Configured warehouse "
                "does not exist."
            )

        incoming_type = (
            data[0].get(
                "in_type_id"
            )
        )

        if not incoming_type:
            raise ValueError(
                "Warehouse does not have "
                "an incoming picking type."
            )

        return int(
            incoming_type[0]
        )

    def _set_picking_done_quantities(
        self,
        picking_id: int,
    ) -> None:
        """
        Same stock.move quantity pattern from
        your tested Odoo implementation.
        """

        move_ids = self.execute(
            "stock.move",
            "search",
            [
                [
                    "picking_id",
                    "=",
                    picking_id,
                ]
            ],
        )

        for move_id in move_ids:
            move = self.execute(
                "stock.move",
                "read",
                [move_id],
                fields=[
                    "product_uom_qty",
                ],
            )

            if not move:
                continue

            planned_qty = float(
                move[0].get(
                    "product_uom_qty",
                    0,
                )
                or 0
            )

            self.execute(
                "stock.move",
                "write",
                [move_id],
                {
                    "quantity": planned_qty,
                },
            )

    # ==========================================================
    # PURCHASE
    # ==========================================================

    def _read_purchase_order(
        self,
        purchase_order_id: int,
    ) -> dict[str, Any] | None:
        data = self.execute(
            "purchase.order",
            "read",
            [purchase_order_id],
            fields=[
                "name",
                "state",
                "partner_id",
                "origin",
                "picking_ids",
                "order_line",
            ],
        )

        if not data:
            return None

        po = data[0]

        lines = po.get(
            "order_line",
            [],
        )

        if not lines:
            return None

        line_data = self.execute(
            "purchase.order.line",
            "read",
            [lines[0]],
            fields=[
                "product_id",
                "product_qty",
                "qty_received",
            ],
        )

        if not line_data:
            return None

        line = line_data[0]

        return {
            "purchase_order_id": int(
                purchase_order_id
            ),
            "name": po["name"],
            "mission_id": (
                po.get("origin")
                or ""
            ),
            "vendor_id": int(
                po["partner_id"][0]
            ),
            "product_id": int(
                line["product_id"][0]
            ),
            "quantity": float(
                line.get(
                    "product_qty",
                    0,
                )
                or 0
            ),
            "state": str(
                po.get(
                    "state",
                    "",
                )
            ),
            "received_qty": float(
                line.get(
                    "qty_received",
                    0,
                )
                or 0
            ),
            "picking_ids": [
                int(value)
                for value
                in po.get(
                    "picking_ids",
                    [],
                )
            ],
        }

    def create_purchase_order(
        self,
        mission_id: str,
        vendor_id: int,
        product_id: int,
        quantity: float,
    ) -> tuple[
        dict[str, Any],
        bool,
    ]:
        """
        mission_id is stored in purchase.order.origin
        and acts as our V1 idempotency key.
        """

        existing_ids = self.execute(
            "purchase.order",
            "search",
            [
                [
                    "origin",
                    "=",
                    mission_id,
                ],
                [
                    "partner_id",
                    "=",
                    vendor_id,
                ],
                [
                    "state",
                    "!=",
                    "cancel",
                ],
            ],
            limit=1,
        )

        if existing_ids:
            existing = (
                self._read_purchase_order(
                    int(existing_ids[0])
                )
            )

            if existing is None:
                raise RuntimeError(
                    "Existing purchase order "
                    "could not be read."
                )

            return (
                existing,
                False,
            )

        vendors = (
            self.get_product_vendors(
                product_id
            )
        )

        unit_price = 1.0

        for vendor in vendors:
            if (
                vendor["vendor_id"]
                == vendor_id
            ):
                unit_price = (
                    vendor["price"]
                    or 1.0
                )

                break

        po_id = self.execute(
            "purchase.order",
            "create",
            [
                {
                    "partner_id": (
                        vendor_id
                    ),
                    "origin": (
                        mission_id
                    ),
                    "picking_type_id": (
                        self
                        ._warehouse_in_type_id()
                    ),
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "product_id": (
                                    product_id
                                ),
                                "product_qty": (
                                    quantity
                                ),
                                "price_unit": (
                                    unit_price
                                ),
                            },
                        )
                    ],
                }
            ],
        )

        if isinstance(
            po_id,
            list,
        ):
            po_id = po_id[0]

        result = (
            self._read_purchase_order(
                int(po_id)
            )
        )

        if result is None:
            raise RuntimeError(
                "Created purchase order "
                "could not be read."
            )

        return (
            result,
            True,
        )

    def confirm_purchase_order(
        self,
        purchase_order_id: int,
    ) -> dict[str, Any]:
        current = (
            self._read_purchase_order(
                purchase_order_id
            )
        )

        if current is None:
            raise ValueError(
                "Purchase order not found."
            )

        if current["state"] in {
            "draft",
            "sent",
            "to approve",
        }:
            self.execute(
                "purchase.order",
                "button_confirm",
                [purchase_order_id],
            )

        result = (
            self._read_purchase_order(
                purchase_order_id
            )
        )

        if result is None:
            raise RuntimeError(
                "Purchase order could not "
                "be verified after confirmation."
            )

        return result

    def receive_purchase(
        self,
        purchase_order_id: int,
    ) -> dict[str, Any]:
        po = (
            self._read_purchase_order(
                purchase_order_id
            )
        )

        if po is None:
            raise ValueError(
                "Purchase order not found."
            )

        if po["state"] not in {
            "purchase",
            "done",
        }:
            raise ValueError(
                "Purchase order must be "
                "confirmed before receipt."
            )

        picking_ids = po.get(
            "picking_ids",
            [],
        )

        if not picking_ids:
            raise RuntimeError(
                "Confirmed purchase order "
                "has no incoming receipt."
            )

        receipt_id = int(
            picking_ids[0]
        )

        receipt_data = self.execute(
            "stock.picking",
            "read",
            [receipt_id],
            fields=[
                "name",
                "state",
            ],
        )

        if not receipt_data:
            raise RuntimeError(
                "Incoming receipt not found."
            )

        if (
            receipt_data[0]["state"]
            != "done"
        ):
            self._set_picking_done_quantities(
                receipt_id
            )

            validate_result = self.execute(
                "stock.picking",
                "button_validate",
                [receipt_id],
            )

            if (
                isinstance(
                    validate_result,
                    dict,
                )
                and validate_result.get(
                    "res_model"
                )
            ):
                raise RuntimeError(
                    "Receipt validation opened "
                    "an Odoo wizard."
                )

        result = (
            self._read_purchase_order(
                purchase_order_id
            )
        )

        if result is None:
            raise RuntimeError(
                "Purchase order could not "
                "be read after receipt."
            )

        return result

    # ==========================================================
    # SALES
    # ==========================================================

    def _read_sales_order(
        self,
        sales_order_id: int,
    ) -> dict[str, Any] | None:
        data = self.execute(
            "sale.order",
            "read",
            [sales_order_id],
            fields=[
                "name",
                "state",
                "partner_id",
                "client_order_ref",
                "order_line",
                "picking_ids",
            ],
        )

        if not data:
            return None

        so = data[0]

        lines = so.get(
            "order_line",
            [],
        )

        if not lines:
            return None

        line_data = self.execute(
            "sale.order.line",
            "read",
            [lines[0]],
            fields=[
                "product_id",
                "product_uom_qty",
                "price_unit",
                "price_subtotal",
            ],
        )

        if not line_data:
            return None

        line = line_data[0]

        return {
            "sales_order_id": int(
                sales_order_id
            ),
            "name": so["name"],
            "mission_id": (
                so.get(
                    "client_order_ref"
                )
                or ""
            ),
            "customer_id": int(
                so["partner_id"][0]
            ),
            "product_id": int(
                line["product_id"][0]
            ),
            "quantity": float(
                line.get(
                    "product_uom_qty",
                    0,
                )
                or 0
            ),
            "unit_price": float(line["price_unit"]),
            "net_unit_price": (float(line["price_subtotal"]) / float(line["product_uom_qty"])
                               if line["product_uom_qty"] else 0.0),
            "state": str(
                so.get(
                    "state",
                    "",
                )
            ),
            "picking_ids": [
                int(value)
                for value
                in so.get(
                    "picking_ids",
                    [],
                )
            ],
        }

    def create_sales_order(
        self,
        mission_id: str,
        customer_id: int,
        product_id: int,
        quantity: float,
    ) -> tuple[
        dict[str, Any],
        bool,
    ]:
        existing_ids = self.execute(
            "sale.order",
            "search",
            [
                [
                    "client_order_ref",
                    "=",
                    mission_id,
                ],
                [
                    "state",
                    "!=",
                    "cancel",
                ],
            ],
            limit=1,
        )

        from erp_bar.odoo.sales_pricing import enforce_sales_price

        if existing_ids:
            enforce_sales_price(self, int(existing_ids[0]), allow_update=True)
            existing = (
                self._read_sales_order(
                    int(existing_ids[0])
                )
            )

            if existing is None:
                raise RuntimeError(
                    "Existing sales order "
                    "could not be read."
                )

            return (
                existing,
                False,
            )

        so_id = self.execute(
            "sale.order",
            "create",
            [
                {
                    "partner_id": (
                        customer_id
                    ),
                    "warehouse_id": (
                        self.warehouse_id
                    ),
                    "client_order_ref": (
                        mission_id
                    ),
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "product_id": (
                                    product_id
                                ),
                                "product_uom_qty": (
                                    quantity
                                ),
                            },
                        )
                    ],
                }
            ],
        )

        if isinstance(
            so_id,
            list,
        ):
            so_id = so_id[0]

        enforce_sales_price(self, int(so_id), allow_update=True)

        result = (
            self._read_sales_order(
                int(so_id)
            )
        )

        if result is None:
            raise RuntimeError(
                "Created sales order "
                "could not be read."
            )

        return (
            result,
            True,
        )

    def get_sales_order(
        self,
        sales_order_id: int,
    ) -> dict[str, Any]:
        result = (
            self._read_sales_order(
                sales_order_id
            )
        )

        if result is None:
            raise ValueError(
                "Sales order not found."
            )

        return result

    def confirm_sales_order(
        self,
        sales_order_id: int,
    ) -> dict[str, Any]:
        current = (
            self.get_sales_order(
                sales_order_id
            )
        )

        from erp_bar.odoo.sales_pricing import enforce_sales_price
        enforce_sales_price(self, sales_order_id, allow_update=True)

        if current["state"] in {
            "draft",
            "sent",
        }:
            self.execute(
                "sale.order",
                "action_confirm",
                [sales_order_id],
            )

        enforce_sales_price(self, sales_order_id, allow_update=False)
        return self.get_sales_order(
            sales_order_id
        )

    # ==========================================================
    # DELIVERY
    # ==========================================================

    def _read_delivery(
        self,
        picking_id: int,
    ) -> dict[str, Any] | None:
        pickings = self.execute(
            "stock.picking",
            "read",
            [picking_id],
            fields=[
                "name",
                "state",
                "sale_id",
                "partner_id",
            ],
        )

        if not pickings:
            return None

        picking = pickings[0]

        move_ids = self.execute(
            "stock.move",
            "search",
            [
                [
                    "picking_id",
                    "=",
                    picking_id,
                ]
            ],
            limit=1,
        )

        if not move_ids:
            return None

        move_data = self.execute(
            "stock.move",
            "read",
            [move_ids[0]],
            fields=[
                "product_id",
                "product_uom_qty",
                "quantity",
            ],
        )

        if not move_data:
            return None

        move = move_data[0]

        state = str(
            picking.get(
                "state",
                "",
            )
        )

        planned_qty = float(
            move.get(
                "product_uom_qty",
                0,
            )
            or 0
        )

        actual_qty = float(
            move.get(
                "quantity",
                0,
            )
            or 0
        )

        # Read the move quantity, including partial reservations.
        # A picking status alone must not invent a reserved quantity.
        reserved_qty = (
            actual_qty
            if state not in {"done", "cancel"}
            else 0.0
        )

        delivered_qty = (
            actual_qty
            if state == "done"
            else 0.0
        )

        sale_id = (
            picking.get(
                "sale_id"
            )
        )

        partner_id = (
            picking.get(
                "partner_id"
            )
        )

        return {
            "picking_id": int(
                picking_id
            ),
            "name": (
                picking["name"]
            ),
            "sales_order_id": (
                int(sale_id[0])
                if sale_id
                else 0
            ),
            "customer_id": (
                int(partner_id[0])
                if partner_id
                else 0
            ),
            "product_id": int(
                move["product_id"][0]
            ),
            "quantity": planned_qty,
            "state": state,
            "reserved_qty": (
                reserved_qty
            ),
            "delivered_qty": (
                delivered_qty
            ),
        }

    def get_delivery_for_sales_order(
        self,
        sales_order_id: int,
    ) -> dict[str, Any] | None:
        picking_ids = self.execute(
            "stock.picking",
            "search",
            [
                [
                    "sale_id",
                    "=",
                    sales_order_id,
                ],
                [
                    "state",
                    "!=",
                    "cancel",
                ],
            ],
            limit=1,
        )

        if not picking_ids:
            return None

        return self._read_delivery(
            int(picking_ids[0])
        )

    def check_delivery_availability(
        self,
        picking_id: int,
    ) -> dict[str, Any]:
        delivery = (
            self._read_delivery(
                picking_id
            )
        )

        if delivery is None:
            raise ValueError(
                "Delivery picking not found."
            )

        if delivery["state"] == "cancel":
            raise ValueError("Delivery picking is cancelled.")

        if delivery["state"] == "done":
            available_qty = float(delivery["delivered_qty"])
        else:
            # Warehouse free stock excludes ALL reservations. Add back
            # only the quantity already reserved for this delivery.
            available_qty = (
                self.get_available_stock(delivery["product_id"])
                + float(delivery["reserved_qty"])
            )

        required_qty = float(
            delivery["quantity"]
        )

        return {
            "picking_id": (
                picking_id
            ),
            "required_qty": (
                required_qty
            ),
            "available_qty": (
                available_qty
            ),
            "can_fulfill": (
                available_qty
                >= required_qty
            ),
        }

    def assign_delivery(
        self,
        picking_id: int,
    ) -> dict[str, Any]:
        delivery = (
            self._read_delivery(
                picking_id
            )
        )

        if delivery is None:
            raise ValueError(
                "Delivery picking not found."
            )

        if delivery["state"] == "cancel":
            raise ValueError("Delivery picking is cancelled.")

        if delivery["state"] not in {
            "assigned",
            "done",
        }:
            self.execute(
                "stock.picking",
                "action_assign",
                [picking_id],
            )

        result = (
            self._read_delivery(
                picking_id
            )
        )

        if result is None:
            raise RuntimeError(
                "Delivery could not be verified "
                "after reservation."
            )

        return result

    def validate_delivery(
        self,
        picking_id: int,
    ) -> dict[str, Any]:
        delivery = (
            self._read_delivery(
                picking_id
            )
        )

        if delivery is None:
            raise ValueError(
                "Delivery picking not found."
            )

        if delivery["state"] == "done":
            return delivery

        if delivery["state"] == "cancel":
            raise ValueError("Delivery picking is cancelled.")

        if delivery["state"] != "assigned":
            self.execute(
                "stock.picking",
                "action_assign",
                [picking_id],
            )

            delivery = self._read_delivery(picking_id)

        if (
            delivery is None
            or delivery["state"] != "assigned"
            or float(delivery["reserved_qty"]) < float(delivery["quantity"])
        ):
            raise RuntimeError(
                "Delivery does not have a verified full reservation. "
                "Validation was not attempted."
            )

        self._set_picking_done_quantities(
            picking_id
        )

        validate_result = self.execute(
            "stock.picking",
            "button_validate",
            [picking_id],
        )

        if (
            isinstance(
                validate_result,
                dict,
            )
            and validate_result.get(
                "res_model"
            )
        ):
            raise RuntimeError(
                "Delivery validation opened "
                "an Odoo wizard."
            )

        result = (
            self._read_delivery(
                picking_id
            )
        )

        if result is None:
            raise RuntimeError(
                "Delivery could not be read "
                "after validation."
            )

        return result
