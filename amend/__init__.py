"""Amend: know what changed at your airports every FAA cycle."""

SCHEMA_VERSION = 1

# the version of the code that turns FAA files into changes. bump it in any PR that changes
# what a change says, how it's ranked, or whether it shows up at all, for the same FAA input
# (amend/runlog.py ENGINE_FILES). every new history entry and every run log record carries
# it, so any published change can be traced to the engine that made it. history entries from
# before this field existed have no "engine".
ENGINE_VERSION = "1.2.3"
