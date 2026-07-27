# -*- coding: utf-8 -*-
"""把库内旧障碍物枚举对齐到新前端：pole→power_tower, wind→wind_turbine。"""
from sqlalchemy import create_engine, text

DB_URL = "postgresql://postgres:123456@localhost:5432/detection_platform"

engine = create_engine(DB_URL)
with engine.begin() as db:
    r1 = db.execute(
        text(
            """
            UPDATE data_resources
            SET metadata = jsonb_set(metadata, '{obstacle}', '"power_tower"', true)
            WHERE metadata->>'obstacle' = 'pole'
            """
        )
    )
    r2 = db.execute(
        text(
            """
            UPDATE data_resources
            SET metadata = jsonb_set(metadata, '{obstacle}', '"wind_turbine"', true)
            WHERE metadata->>'obstacle' IN ('wind', 'wind_power')
            """
        )
    )
    print(f"pole -> power_tower: {r1.rowcount}")
    print(f"wind -> wind_turbine: {r2.rowcount}")

    rows = db.execute(
        text(
            """
            SELECT metadata->>'batch_id' AS bid,
                   metadata->>'weather' AS w,
                   metadata->>'time_of_day' AS t,
                   metadata->>'terrain' AS ter,
                   metadata->>'obstacle' AS o,
                   COUNT(*) AS n
            FROM data_resources
            WHERE metadata->>'batch_id' LIKE '%20260430_202854%'
               OR metadata->>'batch_id' LIKE '%20260427_151113%'
            GROUP BY 1,2,3,4,5
            """
        )
    ).mappings()
    print("after update:")
    for row in rows:
        print(dict(row))
