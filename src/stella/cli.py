"""Unified command-line interface: ``python -m stella``.

Every maintained action is reachable through this CLI. Read-only commands
introspect the workflow/operation/schema catalogs; ``workflow plan`` runs a
full plan/preflight without external calls; ``workflow run`` refuses to
execute without ``--execute`` and never treats ``--execute`` as granting
network, LLM, gold, scoring, supersede, or publication authority. Machine
output is stable JSON rendered from the same response models as the human
text view.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from stella import schema_registry, workflows
from stella.workflows import (
    Authorities,
    StellaError,
    WorkflowRequest,
)
from stella import workflow_runtime

ALLOW_FLAGS = {
    "--allow-network": "network",
    "--allow-llm": "llm",
    "--allow-gold-private": "gold_private",
    "--allow-scoring": "scoring",
    "--allow-supersede": "supersede",
    "--allow-publication": "publication",
}


def _json_flag() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--json", action="store_true", help="emit stable JSON")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stella",
        description="Stella literature-to-catalog workflow CLI",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    workflow = commands.add_parser(
        "workflow", parents=[_json_flag()], help="product workflow commands"
    )
    workflow_commands = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_commands.add_parser(
        "list", parents=[_json_flag()], help="list public product workflows"
    )
    show = workflow_commands.add_parser(
        "show", parents=[_json_flag()], help="show one workflow"
    )
    show.add_argument("workflow_id")
    plan = workflow_commands.add_parser(
        "plan", parents=[_json_flag()], help="plan/preflight a workflow request"
    )
    plan.add_argument("workflow_id")
    plan.add_argument("--input", required=True, help="request JSON path")
    run = workflow_commands.add_parser(
        "run", parents=[_json_flag()], help="run a workflow"
    )
    run.add_argument("workflow_id")
    run.add_argument("--input", required=True, help="request JSON path")
    run.add_argument(
        "--execute",
        action="store_true",
        help="execute (never implies other authorities)",
    )
    for flag in ALLOW_FLAGS:
        run.add_argument(flag, action="store_true")

    operation = commands.add_parser(
        "operation", parents=[_json_flag()], help="operation catalog commands"
    )
    operation_commands = operation.add_subparsers(
        dest="operation_command", required=True
    )
    operation_show = operation_commands.add_parser(
        "show", parents=[_json_flag()], help="show one operation"
    )
    operation_show.add_argument("operation_id")

    schema = commands.add_parser(
        "schema", parents=[_json_flag()], help="schema registry commands"
    )
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    schema_commands.add_parser(
        "list", parents=[_json_flag()], help="list schema artifacts"
    )
    schema_show = schema_commands.add_parser(
        "show", parents=[_json_flag()], help="show one schema artifact"
    )
    schema_show.add_argument("schema_name")
    schema_commands.add_parser(
        "generate", parents=[_json_flag()], help="regenerate schema views"
    )
    schema_commands.add_parser(
        "check", parents=[_json_flag()], help="check schema views for drift"
    )
    return parser


def _ok(data: dict[str, Any], as_json: bool) -> int:
    _emit({"status": "ok", "data": data}, as_json)
    return 0


def _error(error: StellaError, as_json: bool) -> int:
    _emit({"status": "error", "error": error.payload()}, as_json)
    return 1


def _emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if payload["status"] == "error":
        error = payload["error"]
        print(f"error [{error['code']}]: {error['message']}")
        if error.get("missing_authority"):
            print("missing authorities: " + ", ".join(error["missing_authority"]))
        if error.get("missing_input"):
            print("missing input: " + ", ".join(error["missing_input"]))
        print(f"next action: {error['next_action']}")
        return
    _render_human(payload["data"])


def _render_human(data: dict[str, Any]) -> None:
    if "workflows" in data:
        for spec in data["workflows"]:
            print(f"{spec['id']}: {spec['human_intents'][0]}")
    elif "operations" in data:
        for spec in data["operations"]:
            print(f"{spec['id']} [{spec['owner']}] authorities={spec['authorities']}")
    elif "schemas" in data:
        for entry in data["schemas"]:
            print(
                f"{entry['name']} v{entry['current_version']} ({entry['lifecycle']})"
            )
    elif "phases" in data:
        print(f"workflow: {data.get('workflow_id')} status: {data.get('status')}")
        for phase in data["phases"]:
            marker = " (optional)" if phase.get("optional") else ""
            print(f"  phase {phase['id']}{marker}: {', '.join(phase['operations'])}")
        print(f"required authorities: {', '.join(data.get('required_authorities', []))}")
        print(f"missing authorities: {', '.join(data.get('missing_authorities', []))}")
    elif "callables" in data:
        print("all operation callables resolve")
    else:
        print(json.dumps(data, indent=2, sort_keys=True))


def _load_request(
    workflow_id: str, input_path: str, overrides: dict[str, bool]
) -> WorkflowRequest:
    spec = workflows.get_workflow(workflow_id)
    try:
        with open(input_path, encoding="utf-8") as handle:
            raw = json.loads(handle.read())
    except FileNotFoundError as error:
        raise StellaError(
            "INVALID_INPUT",
            f"input file not found: {input_path}",
            missing_input=[input_path],
            next_action="provide a request JSON file with --input",
        ) from error
    except json.JSONDecodeError as error:
        raise StellaError(
            "INVALID_INPUT",
            f"input file is not valid JSON: {input_path} ({error})",
            next_action="fix the request JSON",
        ) from error
    if not isinstance(raw, dict):
        raise StellaError(
            "INVALID_INPUT",
            "request must be a JSON object",
            next_action="provide an object with the workflow request fields",
        )
    raw_authorities = raw.get("authorities") or {}
    if not isinstance(raw_authorities, dict):
        raise StellaError(
            "INVALID_INPUT",
            "authorities must be an object of boolean grants",
            next_action="list granted authority kinds explicitly",
        )
    granted = {**raw_authorities, **overrides}
    raw["authorities"] = granted
    model = workflows.resolve_reference(spec.input_model)
    try:
        return model.model_validate(raw)
    except Exception as error:
        raise StellaError(
            "INVALID_INPUT",
            f"request failed validation: {error}",
            missing_input=_validation_error_fields(error),
            next_action="fix the request fields for the workflow input model",
        ) from error


def _validation_error_fields(error: Exception) -> list[str]:
    locators: set[str] = set()
    errors = getattr(error, "errors", lambda: [])()
    for item in errors:
        location = ".".join(str(part) for part in item.get("loc", ()))
        if location:
            locators.add(location)
    return sorted(locators)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    try:
        return _dispatch(args, as_json)
    except StellaError as error:
        return _error(error, as_json)


def _dispatch(args: argparse.Namespace, as_json: bool) -> int:
    command = args.command
    if command == "workflow":
        return _dispatch_workflow(args, as_json)
    if command == "operation":
        if args.operation_command == "show":
            spec = workflows.get_operation(args.operation_id)
            return _ok(spec.model_dump(mode="json"), as_json)
    if command == "schema":
        return _dispatch_schema(args, as_json)
    raise StellaError("INTERNAL", f"unhandled command: {command}")


def _dispatch_workflow(args: argparse.Namespace, as_json: bool) -> int:
    sub = args.workflow_command
    if sub == "list":
        catalog = workflows.load_workflow_catalog()
        return _ok(
            {
                "workflows": [
                    spec.model_dump(mode="json") for spec in catalog.workflows
                ]
            },
            as_json,
        )
    if sub == "show":
        spec = workflows.get_workflow(args.workflow_id)
        return _ok(spec.model_dump(mode="json"), as_json)
    if sub in ("plan", "run"):
        overrides: dict[str, bool] = {}
        if sub == "run":
            for flag, kind in ALLOW_FLAGS.items():
                if getattr(args, flag.lstrip("-").replace("-", "_")):
                    overrides[kind] = True
            if args.execute:
                overrides["execute"] = True
        request = _load_request(args.workflow_id, args.input, overrides)
        plan = workflow_runtime.plan_workflow(
            root=workflows.DEFAULT_ROOT,
            workflow_id=args.workflow_id,
            request=request,
        )
        if sub == "plan":
            return _ok(plan, as_json)
        if not args.execute:
            raise StellaError(
                "EXECUTE_REQUIRED",
                "workflow run refuses to execute without --execute",
                next_action=(
                    "re-run with --execute and the explicit authority flags "
                    "reported by workflow plan"
                ),
            )
        missing = workflow_runtime.check_execution_authorities(plan)
        if missing:
            raise StellaError(
                "MISSING_AUTHORITY",
                "execution is blocked by missing authorities",
                missing_authority=missing,
                next_action="grant each authority explicitly with its --allow flag",
            )
        phases = workflow_runtime.resolve_phases(
            workflows.get_workflow(args.workflow_id),
            getattr(request, "phases", None),
        )
        operations = workflow_runtime.operations_for_phases(
            phases, workflows.DEFAULT_ROOT
        )
        workflow_runtime.resolve_operation_callables(operations)
        raise StellaError(
            "OPERATION_NOT_IMPLEMENTED",
            (
                "operation execution adapters are not wired yet for "
                f"{args.workflow_id}"
            ),
            next_action="wire the workflow adapter in its owner package",
        )
    raise StellaError("INTERNAL", f"unhandled workflow command: {sub}")


def _dispatch_schema(args: argparse.Namespace, as_json: bool) -> int:
    sub = args.schema_command
    if sub == "list":
        return _ok({"schemas": schema_registry.list_schema_status()}, as_json)
    if sub == "show":
        for entry in schema_registry.list_schema_status():
            if entry["name"] == args.schema_name:
                return _ok(entry, as_json)
        raise StellaError(
            "UNKNOWN_SCHEMA",
            f"unknown schema artifact: {args.schema_name}",
            next_action="run 'python -m stella schema list --json'",
        )
    if sub in ("generate", "check"):
        handler = getattr(schema_registry, "generate_views", None)
        if sub == "check":
            handler = getattr(schema_registry, "check_views", None)
        if handler is None:
            raise StellaError(
                "OPERATION_NOT_IMPLEMENTED",
                f"schema {sub} is not implemented yet",
                next_action="implement schema views in stella.schema_registry",
            )
        return _ok(handler(), as_json)
    raise StellaError("INTERNAL", f"unhandled schema command: {sub}")


if __name__ == "__main__":
    sys.exit(main())
