"""Active and legacy benchmark extraction entrypoint policy."""

from __future__ import annotations

from .task_surfaces import CORE_PROV, FULL

PRIMARY_DIRECT_METHOD = "B"
PRIMARY_TASK_SURFACE = CORE_PROV
LEGACY_DIRECT_METHODS = ("C",)
LEGACY_TASK_SURFACES = (FULL,)


def require_legacy_opt_in(
    *,
    method: str,
    task_surface: str,
    allow_legacy_method_c: bool = False,
    allow_legacy_full: bool = False,
) -> None:
    """Reject accidental use of retained Method C/FULL implementation paths."""

    normalized_method = str(method).upper()
    normalized_surface = str(task_surface)
    if normalized_method not in {PRIMARY_DIRECT_METHOD, *LEGACY_DIRECT_METHODS}:
        raise ValueError(
            f"unsupported direct benchmark method {method!r}; expected "
            f"{PRIMARY_DIRECT_METHOD} or an explicit legacy method"
        )
    if normalized_method in LEGACY_DIRECT_METHODS and not allow_legacy_method_c:
        raise ValueError(
            "Method C is legacy; pass --allow-legacy-method-c only for an "
            "explicitly authorized historical diagnostic or future extension"
        )
    if normalized_surface in LEGACY_TASK_SURFACES and not allow_legacy_full:
        raise ValueError(
            "FULL is legacy; pass --allow-legacy-full only for an explicitly "
            "authorized historical diagnostic or future extension"
        )
    if normalized_surface not in {PRIMARY_TASK_SURFACE, *LEGACY_TASK_SURFACES}:
        raise ValueError(f"unsupported task surface {task_surface!r}")
