import os

from dotenv import load_dotenv

from erp_bar.odoo.client import (
    get_odoo_bridge,
)


load_dotenv()


def main():
    bridge = get_odoo_bridge()

    print()
    print("=" * 60)
    print("ODOO CONNECTION")
    print("=" * 60)

    # ==========================================================
    # CONNECTION / CONFIG
    # ==========================================================

    config = (
        bridge
        .validate_runtime_configuration()
    )

    print(
        "UID:",
        config["uid"],
    )

    print(
        "Customer:",
        config["customer_id"],
        "-",
        config["customer_name"],
    )

    print(
        "Warehouse:",
        config["warehouse_id"],
        "-",
        config["warehouse_name"],
    )

    # ==========================================================
    # CONFIGURED PRODUCT TEMPLATE
    # ==========================================================

    product_template_id = int(
        os.environ[
            "ODOO_PRODUCT_TEMPLATE_ID"
        ]
    )

    print()
    print(
        "Configured product template:",
        product_template_id,
    )

    # ==========================================================
    # RESOLVE PRODUCT VARIANT
    # ==========================================================

    product_id = (
        bridge.get_variant_id(
            product_template_id
        )
    )

    print(
        "Resolved product.product ID:",
        product_id,
    )

    product = bridge._read_product(
        product_id
    )

    if product is None:
        raise RuntimeError(
            "Configured product could not "
            "be read."
        )

    print()
    print("=" * 60)
    print("PRODUCT")
    print("=" * 60)

    print(
        "ID:",
        product["product_id"],
    )

    print(
        "Name:",
        product["name"],
    )

    print(
        "SKU:",
        product["sku"],
    )

    print(
        "Template ID:",
        product[
            "product_template_id"
        ],
    )

    # ==========================================================
    # STOCK
    # ==========================================================

    stock = (
        bridge.get_available_stock(
            product_id
        )
    )

    print()
    print("=" * 60)
    print("STOCK")
    print("=" * 60)

    print(
        "Available:",
        stock,
    )

    # ==========================================================
    # VENDORS
    # ==========================================================

    vendors = (
        bridge.get_product_vendors(
            product_id
        )
    )

    print()
    print("=" * 60)
    print("VENDORS")
    print("=" * 60)

    if not vendors:
        print(
            "No configured vendors found."
        )

    else:
        for vendor in vendors:
            print(vendor)

    # ==========================================================
    # PRODUCT SEARCH
    # ==========================================================

    print()
    print("=" * 60)
    print("PRODUCT SEARCH")
    print("=" * 60)

    # Test our new natural-language product
    # resolution using the actual Odoo product name.
    search_result = (
        bridge.search_product(
            product["name"]
        )
    )

    print(
        "Search result:",
        search_result,
    )

    if search_result is None:
        raise RuntimeError(
            "Product search failed."
        )

    if (
        search_result[
            "product_id"
        ]
        != product_id
    ):
        raise RuntimeError(
            "Product search returned a "
            "different product."
        )

    print()
    print("=" * 60)
    print("READ-ONLY ODOO TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()