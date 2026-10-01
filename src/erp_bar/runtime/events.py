"""Optional, request-local observations. Observers never choose agent actions."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import os
import re
import time
from uuid import uuid4
from erp_bar.runtime.model_json import parse_model_object

_sink = ContextVar("erp_bar_event_sink", default=None)
_model_call = ContextVar("erp_bar_model_call", default=None)
_agent = ContextVar("erp_bar_event_agent", default="supervisor")


def clean_text(value, limit=600):
    value = str(value)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in ("PASSWORD", "SECRET", "TOKEN", "API_KEY")) and len(secret) >= 4:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"<think>.*?(?:</think>|$)", "", value, flags=re.S | re.I)
    return value[:limit]


def emit(kind, **data):
    sink = _sink.get()
    if sink is not None:
        try:
            sink({"kind": kind, "agent": _agent.get(), **data})
        except Exception:
            # A disconnected UI cannot turn a successful ERP write into a retry.
            pass


@contextmanager
def event_sink(sink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def agent_scope(agent):
    token = _agent.set(str(agent))
    try:
        yield
    finally:
        _agent.reset(token)


def emit_model_stream(kind, **data):
    emit(kind, stream_id=_model_call.get(), **data)


def emit_summary(message):
    emit("decision_summary", stream_id=_model_call.get(), message=message, validated=False)


def observed_model(function):
    @wraps(function)
    def call(*args, **kwargs):
        start = time.monotonic()
        stream_id = uuid4().hex
        token = _model_call.set(stream_id)
        emit("thinking", stream_id=stream_id, message="Reading the current mission context and selecting the next action.")
        try:
            response = function(*args, **kwargs)
        except Exception:
            emit("model_error", stream_id=stream_id, message="The model request failed. The workflow will handle the failure.")
            raise
        finally:
            _model_call.reset(token)
        emit("model_complete", stream_id=stream_id, duration=round(time.monotonic() - start, 2))
        # The observer and agents must agree on whether the reply is one JSON object.
        try:
            proposal = parse_model_object(response)
            if isinstance(proposal, dict) and isinstance(proposal.get("reason"), str):
                emit("proposal", stream_id=stream_id, action=clean_text(proposal.get("action") or proposal.get("capability") or "Proposal", 80),
                     message=clean_text(proposal["reason"]), validated=False)
        except (ValueError, TypeError):
            pass
        return response
    return call


def observe_step(entry):
    # Only actual decisions are recorded here, never eligibility probes.
    if entry.get("approved") is False:
        emit("checkpoint_rejected", action=clean_text(entry.get("action", "Proposal"), 80),
             message=clean_text(entry.get("feedback") or "The proposal did not pass Python validation."))


def public_result(result):
    value = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
    if not isinstance(value, dict):
        return {}
    # Explicit allowlist: no credentials, connection details, raw errors or input prompts.
    allowed = {"product_id", "available_qty", "received_qty", "created", "vendor_id",
               "sales_order_id", "purchase_order_id", "picking_id", "unit_price", "net_unit_price",
               "state", "quantity", "delivered_qty", "reserved_qty", "supplierinfo_id"}
    summary = {key: value[key] for key in allowed if key in value and isinstance(value[key], (str, int, float, bool, type(None)))}
    for key in ("product", "purchase_order", "sales_order", "delivery"):
        if isinstance(value.get(key), dict):
            summary.update({k: v for k, v in value[key].items() if k in allowed and isinstance(v, (str, int, float, bool, type(None)))})
    if isinstance(value.get("vendors"), list):
        summary["supplier_count"] = len(value["vendors"])
    return summary


def observed_tool(function):
    @wraps(function)
    def call(*args, **kwargs):
        name = function.__name__
        start = time.monotonic()
        # Only known record IDs are shared with the optional Odoo display.
        tool_input = args[0] if args else kwargs.get("tool_input")
        record_ids = {}
        for key in ("product_id", "sales_order_id", "purchase_order_id", "picking_id"):
            value = getattr(tool_input, key, None)
            if type(value) is int and value > 0:
                record_ids[key] = value
        emit("tool_start", action=name, message=name.replace("_", " ").capitalize(), record_ids=record_ids)
        try:
            result = function(*args, **kwargs)
        except Exception:
            emit("tool_end", action=name, ok=False, message="Tool execution failed; see the local console for details.",
                 duration=round(time.monotonic() - start, 2), result={})
            raise
        value = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        ok = isinstance(value, dict) and value.get("ok") is True
        emit("tool_end", action=name, ok=ok, result=public_result(value),
             message="Tool returned a successful result." if ok else "Tool reported an unsuccessful result.",
             duration=round(time.monotonic() - start, 2))
        return result
    return call


def mission_snapshot(mission):
    return {"status": str(mission.status), "sales_order_id": mission.sales_order_id,
            "purchase_order_ids": list(mission.purchase_order_ids), "delivery_id": mission.delivery_picking_id,
            "customer_message": clean_text(mission.customer_message, 1200) if mission.customer_message else None}


def observed_agent(agent):
    def decorate(function):
        @wraps(function)
        def call(state, *args, **kwargs):
            with agent_scope(agent):
                emit("agent_start", message="Assessing the mission.")
                result = function(state, *args, **kwargs)
                mission = result["mission"]
                decision = result.get("last_agent_decision")
                summary = "Agent task completed."
                if decision is not None and str(decision.decision) in {"MISSION_FAILED", "PROCUREMENT_FAILED"}:
                    summary = "The task could not be completed. Sales will provide the final customer response."
                elif decision is not None and not decision.facts.get("runtime_failure"):
                    summary = clean_text(decision.reason)
                emit("agent_end", message=summary,
                     decision=str(decision.decision) if decision is not None else None,
                     **mission_snapshot(mission))
                if str(mission.status) == "FAILED" and not mission.customer_response_prepared:
                    emit("handoff", source=str(agent), target="sales_agent", message="Prepare the final customer response.")
                elif not mission.is_terminal():
                    if str(agent) == "supervisor":
                        from erp_bar.orchestrator.agent_registry import get_agent_for_capability
                        delegation = result.get("supervisor_decision")
                        if delegation is not None:
                            emit("handoff", source="supervisor", target=str(get_agent_for_capability(delegation.requested_capability)),
                                 action=str(delegation.requested_capability), message=clean_text(delegation.reason))
                    else:
                        emit("handoff", source=str(agent), target="supervisor", message="Return verified results to the supervisor.")
                return result
        return call
    return decorate
