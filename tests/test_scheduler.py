import asyncio
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.scheduler import (
    parse_schedule_expression,
    get_next_cron_run,
    get_tehran_now,
    create_scheduled_job_async,
    list_scheduled_jobs_async,
    cancel_scheduled_job_async
)
from src.core import database


async def mock_execute_d1_query(sql: str, params: list = None):
    """In-memory mock D1 executor for offline test validation."""
    if not hasattr(mock_execute_d1_query, "store"):
        mock_execute_d1_query.store = []
        mock_execute_d1_query.next_id = 1

    sql_upper = sql.upper().strip()
    if "INSERT INTO SCHEDULED_JOBS" in sql_upper:
        jid = mock_execute_d1_query.next_id
        mock_execute_d1_query.next_id += 1
        record = {
            "id": jid,
            "chat_id": params[0],
            "user_id": params[1],
            "user_name": params[2],
            "username": params[3],
            "title": params[4],
            "action_type": params[5],
            "payload": params[6],
            "schedule_type": params[7],
            "interval_seconds": params[8],
            "cron_expr": params[9],
            "next_run_ts": params[10],
            "is_recurring": params[11],
            "timezone": params[12] if len(params) > 12 else "Asia/Tehran",
            "status": "active"
        }
        mock_execute_d1_query.store.append(record)
        return {"success": True, "results": []}

    if "LAST_INSERT_ROWID" in sql_upper:
        return {"success": True, "results": [{"id": mock_execute_d1_query.next_id - 1}]}

    if "COUNT(*) AS CNT" in sql_upper:
        uid = params[0]
        cnt = sum(1 for r in mock_execute_d1_query.store if r["user_id"] == uid and r["status"] == "active")
        return {"success": True, "results": [{"cnt": cnt}]}

    if "SELECT * FROM SCHEDULED_JOBS WHERE USER_ID" in sql_upper:
        uid = params[0]
        rows = [r for r in mock_execute_d1_query.store if r["user_id"] == uid and r["status"] == "active"]
        return {"success": True, "results": rows}

    if "SELECT ID, USER_ID, TITLE FROM SCHEDULED_JOBS WHERE ID" in sql_upper:
        jid = params[0]
        rows = [r for r in mock_execute_d1_query.store if r["id"] == jid]
        return {"success": True, "results": rows}

    if "UPDATE SCHEDULED_JOBS SET STATUS = 'CANCELLED'" in sql_upper:
        jid = params[0]
        for r in mock_execute_d1_query.store:
            if r["id"] == jid:
                r["status"] = "cancelled"
        return {"success": True, "results": []}

    return {"success": True, "results": []}


async def main():
    print("--- 1. Testing Natural Time & Cron Parsing ---")
    now = get_tehran_now()
    
    # 10m
    ts, is_rec, _, sec, desc = parse_schedule_expression("10m", now)
    assert sec == 600
    assert not is_rec
    print("✓ 10m passed:", desc)

    # Persian relative
    ts, is_rec, _, sec, desc = parse_schedule_expression("۱۵ دقیقه دیگه", now)
    assert sec == 900
    assert not is_rec
    print("✓ ۱۵ دقیقه دیگه passed:", desc)

    # Recurring interval
    ts, is_rec, _, sec, desc = parse_schedule_expression("هر ۲ ساعت", now)
    assert sec == 7200
    assert is_rec
    print("✓ هر ۲ ساعت passed:", desc)

    # Daily fixed time
    ts, is_rec, cron, _, desc = parse_schedule_expression("هر روز ساعت ۱۲:۰۰", now)
    assert is_rec
    assert cron == "0 12 * * *"
    print("✓ هر روز ساعت ۱۲:۰۰ passed:", desc)

    # Standard Cron
    ts, is_rec, cron, _, desc = parse_schedule_expression("*/30 * * * *", now)
    assert is_rec
    assert cron == "*/30 * * * *"
    print("✓ */30 * * * * passed:", desc)

    # International Timezone: London
    sched_london = parse_schedule_expression("at 14:00 London time")
    assert sched_london.timezone == "Europe/London"
    print("✓ at 14:00 London time passed:", sched_london.human_desc, f"[{sched_london.timezone}]")

    # International Timezone: Dubai in Persian
    sched_dubai = parse_schedule_expression("فردا ساعت ۵ عصر به وقت دبی")
    assert sched_dubai.timezone == "Asia/Dubai"
    print("✓ فردا ساعت ۵ عصر به وقت دبی passed:", sched_dubai.human_desc, f"[{sched_dubai.timezone}]")

    # International Timezone: New York EST
    sched_ny = parse_schedule_expression("at 9 am est")
    assert sched_ny.timezone == "America/New_York"
    print("✓ at 9 am est passed:", sched_ny.human_desc, f"[{sched_ny.timezone}]")

    print("\n--- 2. Testing Job Creation & D1 Storage ---")
    database.execute_d1_query = mock_execute_d1_query

    res = await create_scheduled_job_async(
        chat_id=1001,
        user_id=5001,
        title="آب دادن به گل‌ها",
        time_expression="10m",
        user_name="علی",
        username="ali_test"
    )
    assert res["success"]
    job_id = res["job_id"]
    print(f"✓ Job created successfully with id #{job_id}: {res['title']} at {res['next_run_formatted']}")

    # Create an international job (London)
    res_int = await create_scheduled_job_async(
        chat_id=1001,
        user_id=5001,
        title="London Team Sync",
        time_expression="at 15:00 London time",
        user_name="Ali",
        username="ali_test"
    )
    assert res_int["success"]
    assert res_int["timezone"] == "Europe/London"
    print(f"✓ International job created successfully: {res_int['title']} at {res_int['next_run_formatted']}")

    # Create 3 more to test quota (already 2 created)
    for i in range(3, 6):
        r = await create_scheduled_job_async(
            chat_id=1001,
            user_id=5001,
            title=f"تسک شماره {i}",
            time_expression=f"{i*10}m",
        )
        assert r["success"]

    # 6th should be rejected for non-admin
    r6 = await create_scheduled_job_async(
        chat_id=1001,
        user_id=5001,
        title="تسک شماره ۶ (اضافی)",
        time_expression="1h",
    )
    assert not r6["success"]
    print("✓ Quota limit enforced (max 5 active jobs):", r6["error"])

    print("\n--- 3. Testing Job Listing ---")
    jobs = await list_scheduled_jobs_async(chat_id=1001, user_id=5001, is_admin=False)
    assert len(jobs) == 5
    print(f"✓ Successfully listed {len(jobs)} active jobs.")

    print("\n--- 4. Testing Job Cancellation ---")
    ok, msg = await cancel_scheduled_job_async(job_id=job_id, caller_id=5001)
    assert ok
    print("✓ Cancellation succeeded:", msg)

    jobs_after = await list_scheduled_jobs_async(chat_id=1001, user_id=5001, is_admin=False)
    assert len(jobs_after) == 4
    print(f"✓ Active jobs count decreased to {len(jobs_after)} after cancellation.")

    print("\n== test_scheduler ALL PASSED ==")


if __name__ == "__main__":
    asyncio.run(main())
