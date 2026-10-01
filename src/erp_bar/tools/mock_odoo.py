from erp_bar.tools.delivery_schemas import (
    DeliveryRecord,
)
from erp_bar.tools.inventory_schemas import (
    ProductRecord,
)
from erp_bar.tools.purchase_schemas import (
    PurchaseOrderRecord,
    VendorRecord,
)
from erp_bar.tools.sales_schemas import (
    SalesOrderRecord,
)


class MockOdoo:
    """
    Temporary in-memory ERP backend.

    Later the methods behind these tools will be
    replaced by real Odoo XML-RPC implementations.

    Pydantic input/output contracts should remain
    stable.
    """

    def __init__(
        self,
    ):
        # ==================================================
        # CUSTOMERS
        # ==================================================

        self.customers: dict[
            int,
            str,
        ] = {
            17: "Demo Customer",
        }

        # ==================================================
        # PRODUCTS
        # ==================================================

        self.products: dict[
            int,
            ProductRecord,
        ] = {
            42: ProductRecord(
                product_id=42,
                name="Product X",
                sku="PROD-X",
            ),
            43: ProductRecord(
                product_id=43,
                name="Product Y",
                sku="PROD-Y",
            ),
        }

        self.stock: dict[
            int,
            float,
        ] = {
            42: 2.0,
            43: 10.0,
        }

        self.next_product_id = 100

        # ==================================================
        # VENDORS
        # ==================================================

        self.vendors: dict[
            int,
            VendorRecord,
        ] = {
            9: VendorRecord(
                vendor_id=9,
                name="Demo Supplier",
            ),
        }

        self.product_vendors: dict[
            int,
            list[int],
        ] = {
            42: [9],
            43: [9],
        }

        # ==================================================
        # PURCHASE ORDERS
        # ==================================================

        self.purchase_orders: dict[
            int,
            PurchaseOrderRecord,
        ] = {}

        self.next_purchase_order_id = 88

        # ==================================================
        # SALES ORDERS
        # ==================================================

        self.sales_orders: dict[
            int,
            SalesOrderRecord,
        ] = {}

        self.next_sales_order_id = 120

        # ==================================================
        # DELIVERIES
        # ==================================================

        self.deliveries: dict[
            int,
            DeliveryRecord,
        ] = {}

        self.next_picking_id = 500

    # ==================================================
    # PRODUCT / INVENTORY
    # ==================================================

    def search_product(
        self,
        query: str,
    ) -> ProductRecord | None:
        normalized = (
            query.strip().casefold()
        )

        for product in (
            self.products.values()
        ):
            if (
                product.name.casefold()
                == normalized
            ):
                return product

            if (
                product.sku is not None
                and product.sku.casefold()
                == normalized
            ):
                return product

        return None

    def create_product(
        self,
        name: str,
        sku: str | None = None,
    ) -> ProductRecord:
        existing = self.search_product(
            name
        )

        if existing is not None:
            return existing

        product_id = (
            self.next_product_id
        )

        self.next_product_id += 1

        product = ProductRecord(
            product_id=product_id,
            name=name,
            sku=sku,
        )

        self.products[
            product_id
        ] = product

        self.stock[
            product_id
        ] = 0.0

        return product

    def get_available_stock(
        self,
        product_id: int,
    ) -> float:
        return self.stock.get(
            product_id,
            0.0,
        )

    # ==================================================
    # VENDORS
    # ==================================================

    def get_product_vendors(
        self,
        product_id: int,
    ) -> list[VendorRecord]:
        vendor_ids = (
            self.product_vendors.get(
                product_id,
                [],
            )
        )

        return [
            self.vendors[vendor_id]
            for vendor_id in vendor_ids
            if vendor_id in self.vendors
        ]

    # ==================================================
    # PURCHASE ORDERS
    # ==================================================

    def find_existing_purchase_order(
        self,
        mission_id: str,
        vendor_id: int,
        product_id: int,
    ) -> PurchaseOrderRecord | None:
        for purchase_order in (
            self.purchase_orders.values()
        ):
            if (
                purchase_order.mission_id
                == mission_id
                and purchase_order.vendor_id
                == vendor_id
                and purchase_order.product_id
                == product_id
            ):
                return purchase_order

        return None

    def create_purchase_order(
        self,
        mission_id: str,
        vendor_id: int,
        product_id: int,
        quantity: float,
    ) -> tuple[
        PurchaseOrderRecord,
        bool,
    ]:
        existing = (
            self.find_existing_purchase_order(
                mission_id=mission_id,
                vendor_id=vendor_id,
                product_id=product_id,
            )
        )

        if existing is not None:
            return (
                existing,
                False,
            )

        purchase_order_id = (
            self.next_purchase_order_id
        )

        self.next_purchase_order_id += 1

        purchase_order = (
            PurchaseOrderRecord(
                purchase_order_id=(
                    purchase_order_id
                ),
                name=(
                    f"P{purchase_order_id:05d}"
                ),
                mission_id=mission_id,
                vendor_id=vendor_id,
                product_id=product_id,
                quantity=quantity,
                state="draft",
                received_qty=0,
            )
        )

        self.purchase_orders[
            purchase_order_id
        ] = purchase_order

        return (
            purchase_order,
            True,
        )

    def confirm_purchase_order(
        self,
        purchase_order_id: int,
    ) -> PurchaseOrderRecord | None:
        purchase_order = (
            self.purchase_orders.get(
                purchase_order_id
            )
        )

        if purchase_order is None:
            return None

        if purchase_order.state == "draft":
            purchase_order.state = "purchase"

        return purchase_order

    def receive_purchase(
        self,
        purchase_order_id: int,
    ) -> PurchaseOrderRecord | None:
        purchase_order = (
            self.purchase_orders.get(
                purchase_order_id
            )
        )

        if purchase_order is None:
            return None

        if purchase_order.state not in {
            "purchase",
            "done",
        }:
            return None

        if (
            purchase_order.received_qty
            < purchase_order.quantity
        ):
            quantity_to_receive = (
                purchase_order.quantity
                - purchase_order.received_qty
            )

            current_stock = (
                self.stock.get(
                    purchase_order.product_id,
                    0.0,
                )
            )

            self.stock[
                purchase_order.product_id
            ] = (
                current_stock
                + quantity_to_receive
            )

            purchase_order.received_qty = (
                purchase_order.quantity
            )

        purchase_order.state = "done"

        return purchase_order

    # ==================================================
    # SALES ORDERS
    # ==================================================

    def find_existing_sales_order(
        self,
        mission_id: str,
    ) -> SalesOrderRecord | None:
        for sales_order in (
            self.sales_orders.values()
        ):
            if (
                sales_order.mission_id
                == mission_id
            ):
                return sales_order

        return None

    def create_sales_order(
        self,
        mission_id: str,
        customer_id: int,
        product_id: int,
        quantity: float,
    ) -> tuple[
        SalesOrderRecord,
        bool,
    ]:
        existing = (
            self.find_existing_sales_order(
                mission_id
            )
        )

        if existing is not None:
            return (
                existing,
                False,
            )

        if (
            customer_id
            not in self.customers
        ):
            raise ValueError(
                "CUSTOMER_NOT_FOUND"
            )

        if (
            product_id
            not in self.products
        ):
            raise ValueError(
                "PRODUCT_NOT_FOUND"
            )

        sales_order_id = (
            self.next_sales_order_id
        )

        self.next_sales_order_id += 1

        sales_order = SalesOrderRecord(
            sales_order_id=(
                sales_order_id
            ),
            name=(
                f"S{sales_order_id:05d}"
            ),
            mission_id=mission_id,
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            state="draft",
        )

        self.sales_orders[
            sales_order_id
        ] = sales_order

        return (
            sales_order,
            True,
        )

    def get_sales_order(
        self,
        sales_order_id: int,
    ) -> SalesOrderRecord | None:
        return self.sales_orders.get(
            sales_order_id
        )

    def confirm_sales_order(
        self,
        sales_order_id: int,
    ) -> SalesOrderRecord | None:
        sales_order = (
            self.sales_orders.get(
                sales_order_id
            )
        )

        if sales_order is None:
            return None

        if sales_order.state == "draft":
            sales_order.state = "sale"

        # In Odoo, confirming a sales order generally
        # causes delivery stock.picking records to be
        # generated by stock rules.
        #
        # We simulate that behavior here.
        self._ensure_delivery_for_sales_order(
            sales_order
        )

        return sales_order

    # ==================================================
    # DELIVERY / STOCK PICKING
    # ==================================================

    def _ensure_delivery_for_sales_order(
        self,
        sales_order: SalesOrderRecord,
    ) -> DeliveryRecord:
        existing = (
            self.get_delivery_for_sales_order(
                sales_order.sales_order_id
            )
        )

        if existing is not None:
            return existing

        picking_id = (
            self.next_picking_id
        )

        self.next_picking_id += 1

        delivery = DeliveryRecord(
            picking_id=picking_id,
            name=f"WH/OUT/{picking_id:05d}",
            sales_order_id=(
                sales_order.sales_order_id
            ),
            customer_id=(
                sales_order.customer_id
            ),
            product_id=(
                sales_order.product_id
            ),
            quantity=(
                sales_order.quantity
            ),
            state="confirmed",
            reserved_qty=0,
            delivered_qty=0,
        )

        self.deliveries[
            picking_id
        ] = delivery

        return delivery

    def get_delivery_for_sales_order(
        self,
        sales_order_id: int,
    ) -> DeliveryRecord | None:
        for delivery in (
            self.deliveries.values()
        ):
            if (
                delivery.sales_order_id
                == sales_order_id
            ):
                return delivery

        return None

    def get_delivery(
        self,
        picking_id: int,
    ) -> DeliveryRecord | None:
        return self.deliveries.get(
            picking_id
        )

    def check_delivery_availability(
        self,
        picking_id: int,
    ) -> tuple[
        DeliveryRecord | None,
        float,
        bool,
    ]:
        delivery = self.get_delivery(
            picking_id
        )

        if delivery is None:
            return (
                None,
                0.0,
                False,
            )

        available_qty = (
            self.stock.get(
                delivery.product_id,
                0.0,
            )
        )

        can_fulfill = (
            available_qty
            >= delivery.quantity
        )

        return (
            delivery,
            available_qty,
            can_fulfill,
        )

    def assign_delivery(
        self,
        picking_id: int,
    ) -> DeliveryRecord | None:
        delivery = self.get_delivery(
            picking_id
        )

        if delivery is None:
            return None

        # Idempotent.
        if delivery.state == "assigned":
            return delivery

        if delivery.state == "done":
            return delivery

        available_qty = (
            self.stock.get(
                delivery.product_id,
                0.0,
            )
        )

        if (
            available_qty
            < delivery.quantity
        ):
            return None

        delivery.reserved_qty = (
            delivery.quantity
        )

        delivery.state = "assigned"

        return delivery

    def validate_delivery(
        self,
        picking_id: int,
    ) -> DeliveryRecord | None:
        delivery = self.get_delivery(
            picking_id
        )

        if delivery is None:
            return None

        # Idempotent re-validation.
        if delivery.state == "done":
            return delivery

        if delivery.state != "assigned":
            return None

        if (
            delivery.reserved_qty
            < delivery.quantity
        ):
            return None

        current_stock = (
            self.stock.get(
                delivery.product_id,
                0.0,
            )
        )

        if (
            current_stock
            < delivery.quantity
        ):
            return None

        # Goods leave the warehouse.
        self.stock[
            delivery.product_id
        ] = (
            current_stock
            - delivery.quantity
        )

        delivery.delivered_qty = (
            delivery.quantity
        )

        delivery.state = "done"

        return delivery


mock_odoo = MockOdoo()