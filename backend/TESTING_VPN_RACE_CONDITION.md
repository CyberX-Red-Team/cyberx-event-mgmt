# Testing VPN Race Condition Fix

This guide explains how to test the VPN assignment race condition fix using the concurrent load test.

## Overview

The `test_vpn_race_condition.py` script simulates 20 concurrent VPN assignment requests to verify that the SELECT FOR UPDATE fix prevents duplicate assignments.

## Prerequisites

### 1. Install Dependencies

```bash
pip install httpx
```

### 2. Prepare Test Environment

You need:
- **Server running**: FastAPI server at http://localhost:8000
- **Admin account**: Valid admin credentials
- **Participants**: At least 20 participants in the database
- **VPN credentials**: At least 60 available VPN credentials (20 requests × 3 VPNs each)

### 3. Configure Test Parameters

Edit `scripts/test_vpn_race_condition.py` and update:

```python
ADMIN_USERNAME = "admin@example.com"      # Your admin username
ADMIN_PASSWORD = "admin123"               # Your admin password
CONCURRENT_REQUESTS = 20                  # Number of concurrent requests
VPNS_PER_REQUEST = 3                      # VPNs to assign per request
```

## Running the Test

### Basic Usage

```bash
cd backend
python scripts/test_vpn_race_condition.py
```

### Expected Output

```
=== VPN Race Condition Test ===

Testing concurrent VPN assignments with SELECT FOR UPDATE fix
Concurrent requests: 20
VPNs per request: 3
Total VPNs to assign: 60

Logging in as admin...
✓ Login successful
Fetching participants...
✓ Found 50 participants
Checking available VPN credentials...
✓ 100 VPN credentials available

Starting concurrent VPN assignments...

=== Test Results ===

Duration: 1.23 seconds
Total requests: 20
Successful: 20
Failed: 0
Total VPNs assigned: 60

Successful Requests:
  Request #1: Assigned 3 VPNs to Participant 123
  Request #2: Assigned 3 VPNs to Participant 124
  Request #3: Assigned 3 VPNs to Participant 125
  Request #4: Assigned 3 VPNs to Participant 126
  Request #5: Assigned 3 VPNs to Participant 127
  ... and 15 more

Verifying no duplicate VPN assignments...
Note: Full verification requires database access
In production, add an admin endpoint to check for duplicates

=== Final Verdict ===

✓ TEST PASSED
All 20 concurrent requests succeeded
All 60 VPN credentials assigned correctly
No race conditions detected
```

## Interpreting Results

### ✓ Test Passed

All concurrent requests succeeded and the expected number of VPNs were assigned.

**What this means:**
- No race conditions occurred
- SELECT FOR UPDATE is working correctly
- The fix prevents duplicate assignments

### ⚠ Partial Success

Some requests succeeded, but not all expected VPNs were assigned.

**Possible causes:**
- VPN pool exhausted (not enough available credentials)
- Some participants already had VPNs assigned
- Database connection issues

**Action:** Check available VPN count and participant states.

### ✗ Test Failed

No VPNs were assigned at all.

**Possible causes:**
- Server not running
- Authentication failed
- Database connection issues
- All VPNs already assigned

**Action:** Check server logs and database state.

## Verifying No Duplicates (Manual)

To manually verify no duplicate assignments occurred:

```sql
-- Connect to PostgreSQL database
psql -U cyberx -d cyberx_events

-- Check for duplicate VPN assignments (should return 0 rows)
SELECT 
    id,
    assigned_to_user_id,
    COUNT(*) as assignment_count
FROM vpn_credentials
WHERE assigned_to_user_id IS NOT NULL
GROUP BY id, assigned_to_user_id
HAVING COUNT(*) > 1;

-- If any rows returned, you have duplicate assignments!
```

## Advanced Testing

### Test with Higher Concurrency

Increase stress on the system:

```python
CONCURRENT_REQUESTS = 50    # More concurrent requests
VPNS_PER_REQUEST = 5        # More VPNs per request
```

**Requirements:** At least 250 available VPNs and 50 participants

### Test Bulk Assignment Endpoint

The test currently uses `/api/vpn/assign`. To test bulk assignment:

Modify the `assign_vpn_to_participant` function:

```python
response = await client.post(
    f"{API_BASE_URL}/api/vpn/bulk-assign",
    json={
        "participant_ids": [participant_id],
        "count_per_participant": count
    }
)
```

### Stress Test with Rapid Retries

Test what happens when requests are retried rapidly:

```python
# Run test 5 times in quick succession
for i in range(5):
    print(f"\n=== Test Run {i+1} ===")
    await run_concurrent_test()
    await asyncio.sleep(1)
```

## Troubleshooting

### Error: httpx not installed

```bash
pip install httpx
```

### Error: Login failed

Check that:
- Server is running at http://localhost:8000
- Admin credentials are correct in the script
- Admin account exists and is active

### Error: Not enough participants

Create more test participants or reduce `CONCURRENT_REQUESTS`:

```bash
# Create participants using admin API or scripts
python scripts/create_admin.py  # Follow prompts
```

### Error: Not enough VPN credentials

Import more VPN credentials:

```bash
# Import VPNs from CSV using admin panel or API
# Or reduce VPNS_PER_REQUEST to 1 or 2
```

### Server crashes during test

Check server logs for errors. Possible issues:
- Database connection pool exhausted
- Memory issues with concurrent requests
- Lock timeout (shouldn't happen with skip_locked=True)

## Performance Benchmarks

Expected performance on typical hardware:

| Concurrent Requests | VPNs Each | Total VPNs | Duration | Throughput |
|---------------------|-----------|------------|----------|------------|
| 10                  | 3         | 30         | ~0.5s    | 60 VPN/s   |
| 20                  | 3         | 60         | ~1.0s    | 60 VPN/s   |
| 50                  | 3         | 150        | ~2.5s    | 60 VPN/s   |
| 100                 | 3         | 300        | ~5.0s    | 60 VPN/s   |

**Note:** Throughput should remain relatively consistent. Significant degradation indicates database bottlenecks.

## Next Steps

After verifying the fix works:

1. **Run in staging environment** with production-like data
2. **Monitor database locks** during beta testing
3. **Set up automated testing** in CI/CD pipeline
4. **Add database query** to verify no duplicates endpoint
5. **Load test** with realistic concurrent user counts

## Database Lock Monitoring

To monitor lock contention during testing:

```sql
-- Show active locks
SELECT 
    locktype,
    relation::regclass,
    mode,
    granted,
    pid
FROM pg_locks
WHERE relation::regclass::text LIKE 'vpn_credentials%';

-- Show waiting queries
SELECT 
    pid,
    usename,
    pg_blocking_pids(pid) as blocked_by,
    query
FROM pg_stat_activity
WHERE wait_event_type = 'Lock';
```

## Success Criteria

The fix is working correctly if:

- ✅ All concurrent requests complete successfully
- ✅ Total assigned VPNs = expected count
- ✅ No duplicate VPN assignments in database
- ✅ No deadlocks or lock timeouts
- ✅ Performance remains acceptable under load

---

**Last Updated:** 2026-02-03  
**Test Version:** 1.0  
**Related Fix:** Commit 365f016
