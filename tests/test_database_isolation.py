import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core import database


async def main():
    print("--- 1. Testing Isolated Per-Group Memory & Search ---")
    group_a = -1001111111111
    group_b = -1002222222222

    # Save message in Group A
    await database.save_message_async(
        chat_id=group_a,
        user_id=101,
        role="user",
        content="رمز عبور محرمانه گروه الف است",
        user_name="علی الف",
        username="ali_a",
        chat_title="گروه الف",
        thread_id=10,
        detected_lang="fa",
        has_media=0
    )

    # Save message in Group B with identical user display name
    await database.save_message_async(
        chat_id=group_b,
        user_id=202,
        role="user",
        content="بحث آزاد گروه ب است",
        user_name="علی ب",
        username="ali_b",
        chat_title="گروه ب",
        thread_id=20,
        detected_lang="fa",
        has_media=1
    )

    # Check RAM isolation
    hist_a = await database.get_chat_context_async(group_a)
    hist_b = await database.get_chat_context_async(group_b)

    assert len(hist_a) == 1
    assert hist_a[0]["content"] == "رمز عبور محرمانه گروه الف است"
    assert hist_a[0]["user_id"] == 101
    assert hist_a[0]["thread_id"] == 10

    assert len(hist_b) == 1
    assert hist_b[0]["content"] == "بحث آزاد گروه ب است"
    assert hist_b[0]["user_id"] == 202
    assert hist_b[0]["thread_id"] == 20
    assert hist_b[0]["has_media"] == 1

    print("✓ Per-group RAM context strictly isolated with enriched metadata.")

    # Search in Group B for keywords from Group A
    search_b = await database.search_group_memory(chat_id=group_b, query="رمز عبور محرمانه")
    assert len(search_b) == 0, "Group B should NEVER see secrets from Group A!"
    print("✓ Cross-group memory leak test passed: Group B search cannot see Group A.")

    search_a = await database.search_group_memory(chat_id=group_a, query="محرمانه")
    assert len(search_a) == 1
    assert search_a[0]["user_id"] == 101
    print("✓ Group A search returns correct internal message.")

    # Zero chat_id search must return empty
    search_zero = await database.search_group_memory(chat_id=0, query="محرمانه")
    assert len(search_zero) == 0
    print("✓ Unspecified chat_id (0) search safely rejected.")

    print("\n--- 2. Testing Per-Chat Display Name Resolution ---")
    # Same display name "رضا" in two different groups
    await database.save_message_async(
        chat_id=group_a,
        user_id=301,
        role="user",
        content="سلام از رضا در گروه الف",
        user_name="رضا رضایی",
        username="reza_a"
    )
    await database.save_message_async(
        chat_id=group_b,
        user_id=402,
        role="user",
        content="سلام از رضا در گروه ب",
        user_name="رضا رضایی",
        username="reza_b"
    )

    # Resolving "رضا" in group A must yield user 301
    res_a = await database.resolve_target_full_identity("رضا رضایی", chat_id=group_a)
    assert res_a["user_id"] == 301, f"Expected 301 in Group A, got {res_a['user_id']}"
    assert res_a["username"] == "reza_a"

    # Resolving "رضا" in group B must yield user 402
    res_b = await database.resolve_target_full_identity("رضا رضایی", chat_id=group_b)
    assert res_b["user_id"] == 402, f"Expected 402 in Group B, got {res_b['user_id']}"
    assert res_b["username"] == "reza_b"

    print("✓ Per-chat display name resolution strictly isolated: no cross-group name overwrite!")

    print("\n--- 3. Testing Cloudflare Rate-Limit Protection & Write-Behind Coalescing ---")
    # Enqueue multiple messages and test flush
    initial_q_size = database._D1_WRITE_QUEUE.qsize()
    for i in range(10):
        await database.save_message_async(
            chat_id=group_a,
            user_id=101,
            role="user",
            content=f"پیام چندگانه تست {i}",
            char_count=len(f"پیام چندگانه تست {i}")
        )
    print(f"✓ {10} messages enqueued without blocking turn execution. Queue size: {database._D1_WRITE_QUEUE.qsize()}")

    # Test flush_write_queue_async
    flushed_count = 0
    original_flush = database._flush_batch_to_d1

    async def mock_flush(batch):
        nonlocal flushed_count
        flushed_count += len(batch)
        print(f"✓ [Cloudflare Saver] Single multi-row D1 insert batch containing {len(batch)} messages!")

    database._flush_batch_to_d1 = mock_flush
    await database.flush_write_queue_async()
    assert flushed_count >= 10
    assert database._D1_WRITE_QUEUE.empty()
    database._flush_batch_to_d1 = original_flush

    print("\n--- 4. Testing Strict Group Authorization (Zero Auto-Approve, Zero Auto-Reject) ---")
    new_group = -1009999999999
    # Simulate non-admin adding bot
    await database.track_group_presence_async(new_group, "گروه تستی جدید", added_by=99999, status="pending")
    assert not database.is_group_approved(new_group)
    assert database.is_group_pending(new_group)
    print("✓ Group registered as pending. Bot is NOT approved to speak.")

    # Even if messages are saved from this group, status stays pending!
    await database.save_message_async(
        chat_id=new_group,
        user_id=888,
        role="user",
        content="پیام در گروه تایید نشده"
    )
    assert not database.is_group_approved(new_group)
    assert database.is_group_pending(new_group)
    print("✓ Incoming messages do NOT auto-approve group: stays strictly pending.")

    # Only when Master Admin explicitly approves:
    await database.set_group_status_async(new_group, "active")
    assert database.is_group_approved(new_group)
    assert not database.is_group_pending(new_group)
    print("✓ Explicit Master Admin approval activates group.")

    print("\n== test_database_isolation ALL PASSED ==")


if __name__ == "__main__":
    asyncio.run(main())
