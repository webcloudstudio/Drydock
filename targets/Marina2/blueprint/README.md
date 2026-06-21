# Marina

A local-first developer control plane that broadcasts project state to a private AWS surface.

## Intent

Marina helps an agentic developer manage many projects without exposing inbound network paths from the
developer workstation. Operations that touch local processes, disk, and project repositories stay on the
workstation. The state worth sharing externally is published to a private AWS surface so trusted members
can read last-known project catalog, capability, and health information even when the workstation is
offline.

Marina standardizes project metadata and capability publication so conformed repositories can be scanned,
published, observed, and later invoked through common contracts rather than per-project integration code.

Every cloud interaction goes through the `marina` Python library so callers remain isolated from direct
AWS service coupling.
