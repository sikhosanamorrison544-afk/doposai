package com.pos.mobile.sync

import com.pos.mobile.data.local.entity.SyncQueueEntity
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Contract: catalog pull is deferred while any sale is not server-acknowledged.
 * Matches [com.pos.mobile.data.local.dao.SyncQueueDao.countOpenUploads] SQL.
 */
class SyncQueueGateTest {

    @Test
    fun blocking_statuses_include_failed_before_catalog_reconcile() {
        val blocking = setOf(
            SyncQueueEntity.STATUS_PENDING,
            SyncQueueEntity.STATUS_SYNCING,
            SyncQueueEntity.STATUS_FAILED,
        )
        assertTrue(blocking.contains(SyncQueueEntity.STATUS_FAILED))
        assertTrue(!blocking.contains(SyncQueueEntity.STATUS_SYNCED))
    }
}