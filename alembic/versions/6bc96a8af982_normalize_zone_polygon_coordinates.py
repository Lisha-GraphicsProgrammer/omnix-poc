"""normalize zone polygon coordinates (issue #26)

Revision ID: 6bc96a8af982
Revises: a36dfdccfd88
Create Date: 2026-08-03

Data-only migration: converts existing Zone.polygon rows from absolute
854x480 zone-editor-canvas pixel coordinates to normalized 0-1 coordinates,
matching the storage format the pipeline scales from at runtime
(run_pipeline.py, issue #26).

This wraps the logic that previously lived in the standalone
migrate_zone_coords_normalize.py script so it now runs as part of the
normal `alembic upgrade head` flow instead of requiring a manual step.

Safe to re-run: any zone whose points are already all within [0, 1] is
assumed to already be normalized and is skipped, so running this twice
won't double-convert (real zones cover meaningful screen area, so a
genuinely un-migrated zone will always have at least one coordinate > 1).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column, Integer
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "6bc96a8af982"
down_revision = "a36dfdccfd88"
branch_labels = None
depends_on = None

VIEW_W, VIEW_H = 854, 480

zones_table = table(
    "zones",
    column("id", Integer),
    column("polygon", JSONB),
)


def _is_already_normalized(polygon) -> bool:
    return all(0 <= p[0] <= 1 and 0 <= p[1] <= 1 for p in polygon)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(zones_table.c.id, zones_table.c.polygon)).fetchall()
    converted = 0
    skipped = 0
    for zone_id, polygon in rows:
        if not polygon or len(polygon) < 3:
            continue
        if _is_already_normalized(polygon):
            skipped += 1
            continue
        new_polygon = [[p[0] / VIEW_W, p[1] / VIEW_H] for p in polygon]
        bind.execute(
            zones_table.update()
            .where(zones_table.c.id == zone_id)
            .values(polygon=new_polygon)
        )
        converted += 1
    print(f"[migration] normalized {converted} zone(s), skipped {skipped} (already normalized)")


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(zones_table.c.id, zones_table.c.polygon)).fetchall()
    reverted = 0
    for zone_id, polygon in rows:
        if not polygon:
            continue
        # Only convert back rows that currently look normalized; mirrors the
        # upgrade's safety check in reverse so downgrade is idempotent too.
        if not _is_already_normalized(polygon):
            continue
        old_polygon = [[p[0] * VIEW_W, p[1] * VIEW_H] for p in polygon]
        bind.execute(
            zones_table.update()
            .where(zones_table.c.id == zone_id)
            .values(polygon=old_polygon)
        )
        reverted += 1
    print(f"[migration] reverted {reverted} zone(s) back to pixel coordinates")
