"""Current mission's observed Odoo references; no extra ERP calls or writes."""


class MissionRecords:
    def __init__(self):
        self.rows = {key: {} for key in ("purchase", "sales", "delivery")}

    def snapshot(self):
        return {key: [dict(row) for row in values.values()] for key, values in self.rows.items()}

    def update(self, event):
        if event.get("kind") == "mission_start":
            self.__init__()
            return True
        if event.get("kind") not in ("tool_end", "agent_end", "mission_end"):
            return False
        before = self.snapshot()
        if event.get("kind") == "tool_end" and event.get("ok") is True:
            result = event.get("result") or {}
            for group, id_key, name_key in (
                ("purchase", "purchase_order_id", "purchase_order_name"),
                ("sales", "sales_order_id", "sales_order_name"),
                ("delivery", "picking_id", "delivery_name"),
            ):
                self.add(group, result.get(id_key), result.get(name_key))
        elif event.get("kind") in ("agent_end", "mission_end"):
            # Mission state supplies genuine IDs even if an earlier tool event
            # is unavailable. Never replace a known reference with an ID alone.
            for record_id in event.get("purchase_order_ids") or []:
                self.add("purchase", record_id)
            self.add("sales", event.get("sales_order_id"))
            self.add("delivery", event.get("delivery_id"))
        return before != self.snapshot()

    def add(self, group, record_id, name=None):
        if type(record_id) is not int or record_id <= 0:
            return
        row = self.rows[group].setdefault(record_id, {"id": record_id, "name": None})
        if isinstance(name, str) and name.strip():
            row["name"] = name
