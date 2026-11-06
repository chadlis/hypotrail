"""The Partition roles of the tool-using agent Track.

`dev` and `public_check` are protocol vocabulary (GLOSSARY: a Partition has a fixed role in the
protocol; Exposure), defined once, here (ADR 0002, amendment of 2026-11-04). A Workload sets which
file holds the Cases of each role, but it cannot add a role: `workload.schema.json` closes `cases`
to these names. `public_check` is touched only through the Exposure journal, which #9 builds.
"""

DEV = "dev"
PUBLIC_CHECK = "public_check"
ROLES = (DEV, PUBLIC_CHECK)
