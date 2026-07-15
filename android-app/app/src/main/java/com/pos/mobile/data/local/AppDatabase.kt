package com.pos.mobile.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import com.pos.mobile.data.local.dao.*
import com.pos.mobile.data.local.entity.*

@Database(
    entities = [
        ProductEntity::class,
        CategoryEntity::class,
        CustomerEntity::class,
        SaleEntity::class,
        SaleItemEntity::class,
        PaymentEntity::class,
        SyncQueueEntity::class,
        SyncMetadataEntity::class,
        ApiCacheEntity::class,
        OfflineMutationEntity::class,
        SupplierEntity::class,
        BranchEntity::class,
        EnterpriseCacheEntity::class,
    ],
    version = 5,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun productDao(): ProductDao
    abstract fun categoryDao(): CategoryDao
    abstract fun customerDao(): CustomerDao
    abstract fun saleDao(): SaleDao
    abstract fun saleItemDao(): SaleItemDao
    abstract fun paymentDao(): PaymentDao
    abstract fun syncQueueDao(): SyncQueueDao
    abstract fun syncMetadataDao(): SyncMetadataDao
    abstract fun apiCacheDao(): ApiCacheDao
    abstract fun offlineMutationDao(): OfflineMutationDao
    abstract fun supplierDao(): SupplierDao
    abstract fun branchDao(): BranchDao
    abstract fun enterpriseCacheDao(): EnterpriseCacheDao

    companion object {
        private const val DB_NAME = "pos_offline.db"

        val MIGRATION_4_5 = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE sync_queue ADD COLUMN clientSaleUuid TEXT")
                db.execSQL(
                    "ALTER TABLE offline_mutations ADD COLUMN retryCount INTEGER NOT NULL DEFAULT 0",
                )
            }
        }

        @Volatile private var instance: AppDatabase? = null
        fun getInstance(context: Context): AppDatabase {
            return instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    DB_NAME
                )
                    .addMigrations(MIGRATION_4_5)
                    .fallbackToDestructiveMigration()
                    .build()
                    .also { instance = it }
            }
        }
    }
}
