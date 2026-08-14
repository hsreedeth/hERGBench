# Repository archive

This directory removes historical material from the active project surface
without deleting it. Archived files remain versioned and recoverable for
scientific or development audit.

- `deprecated_snapshots/` — explicitly deprecated frozen bundles
- `duplicate_configs/` — byte-identical duplicated configuration trees
- `development_notes/` — superseded workspace documentation
- `generated_package_metadata/` — tracked build metadata removed from the
  active source tree

Paths that are still consumed by active code were deliberately not moved.
