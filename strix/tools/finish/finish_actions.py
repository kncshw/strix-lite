from typing import Any

from strix.tools.registry import register_tool


def _validate_content(content: str) -> dict[str, Any] | None:
    if not content or not content.strip():
        return {"success": False, "message": "Content cannot be empty"}
    return None


def _finalize_with_tracer(content: str, success: bool) -> dict[str, Any]:
    try:
        from strix.telemetry.tracer import get_global_tracer

        tracer = get_global_tracer()
        if tracer:
            tracer.set_final_scan_result(
                content=content.strip(),
                success=success,
            )

            return {
                "success": True,
                "scan_completed": True,
                "message": "Scan completed successfully"
                if success
                else "Scan completed with errors",
                "vulnerabilities_found": len(tracer.vulnerability_reports),
            }

        import logging

        logging.warning("Global tracer not available - final scan result not stored")

        return {  # noqa: TRY300
            "success": True,
            "scan_completed": True,
            "message": "Scan completed successfully (not persisted)"
            if success
            else "Scan completed with errors (not persisted)",
            "warning": "Final result could not be persisted - tracer unavailable",
        }

    except ImportError:
        return {
            "success": True,
            "scan_completed": True,
            "message": "Scan completed successfully (not persisted)"
            if success
            else "Scan completed with errors (not persisted)",
            "warning": "Final result could not be persisted - tracer module unavailable",
        }


@register_tool(sandbox_execution=False)
def finish_scan(
    content: str,
    success: bool = True,
    agent_state: Any = None,
) -> dict[str, Any]:
    try:
        validation_error = _validate_content(content)
        if validation_error:
            return validation_error

        return _finalize_with_tracer(content, success)

    except (ValueError, TypeError, KeyError) as e:
        return {"success": False, "message": f"Failed to complete scan: {e!s}"}