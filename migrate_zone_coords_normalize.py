"""
One-time migration for Issue #26: converts existing Zone.polygon rows from
absolute 854x480-canvas pixel coordinates to normalized 0-1 (relative to
frame size) coordinates, matching the new storage format.

Safe to re-run: any zone whose points are already all within [0, 1] is
assumed to already be normalized and is skipped, so running this twice
won't double-convert (real zones cover meaningful screen area, so a
genuinely un-migrated zone will always have at least one coordinate > 1).

Run with:  py migrate_zone_coords_normalize.py
"""
from db.session import SessionLocal
from db.models import Zone

VIEW_W, VIEW_H = 854, 480


def is_already_normalized(polygon) -> bool:
    return all(0 <= p[0] <= 1 and 0 <= p[1] <= 1 for p in polygon)


def main():
    db = SessionLocal()
    try:
        zones = db.query(Zone).all()
        converted = 0
        skipped = 0
        for z in zones:
            if not z.polygon or len(z.polygon) < 3:
                continue
            if is_already_normalized(z.polygon):
                skipped += 1
                continue
            old_polygon = z.polygon
            z.polygon = [[p[0] / VIEW_W, p[1] / VIEW_H] for p in z.polygon]
            print(f"  Zone '{z.name}' (id={z.id}): {old_polygon} -> {z.polygon}")
            converted += 1
        db.commit()
        print(f"\nDone. Converted {converted} zone(s), skipped {skipped} (already normalized).")
    finally:
        db.close()


if __name__ == "__main__":
    main()