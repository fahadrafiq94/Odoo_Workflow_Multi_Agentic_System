import os

from dotenv import load_dotenv

from erp_bar.odoo.client import (
    get_odoo_bridge,
)
from erp_bar.odoo.inventory_service import (
    get_warehouse_stock_snapshot,
)


load_dotenv()


def main():
    bridge = get_odoo_bridge()

    product_template_id = int(
        os.environ[
            "ODOO_PRODUCT_TEMPLATE_ID"
        ]
    )

    product_id = bridge.get_variant_id(
        product_template_id
    )

    snapshot = (
        get_warehouse_stock_snapshot(
            product_id=product_id
        )
    )

    print()
    print("=" * 70)
    print("WAREHOUSE STOCK DIAGNOSTIC")
    print("=" * 70)

    print(
        "Product:",
        snapshot["product_name"],
    )

    print(
        "Product ID:",
        snapshot["product_id"],
    )

    print()
    print(
        "Warehouse:",
        snapshot["warehouse_id"],
        "-",
        snapshot["warehouse_name"],
    )

    print(
        "Stock location:",
        snapshot["stock_location_id"],
        "-",
        snapshot["stock_location_name"],
    )

    print()
    print("=" * 70)
    print("GLOBAL ODOO STOCK")
    print("=" * 70)

    print(
        "qty_available:",
        snapshot[
            "global_qty_available"
        ],
    )

    print(
        "free_qty:",
        snapshot[
            "global_free_qty"
        ],
    )

    print()
    print("=" * 70)
    print("WAREHOUSE STOCK")
    print("=" * 70)

    print(
        "Physical:",
        snapshot["physical_qty"],
    )

    print(
        "Reserved:",
        snapshot["reserved_qty"],
    )

    print(
        "Available for ERP_BAR:",
        snapshot["available_qty"],
    )

    print()
    print("=" * 70)
    print("LOCATION DETAILS")
    print("=" * 70)

    if not snapshot["locations"]:
        print(
            "No warehouse quants found "
            "for this product."
        )

    else:
        for location in (
            snapshot["locations"]
        ):
            print()
            print(
                "Location:",
                location["location_id"],
                "-",
                location["location_name"],
            )

            print(
                "Physical:",
                location["quantity"],
            )

            print(
                "Reserved:",
                location[
                    "reserved_quantity"
                ],
            )

            print(
                "Free:",
                location[
                    "free_quantity"
                ],
            )

    print()
    print("=" * 70)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()