package org.androidmcp.v3fixture

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri

/**
 * Public fixture-only synthetic counter read oracle.
 * No real app data or user content; mutation is explicitly unsupported.
 */
class FixtureOracleProvider : ContentProvider() {
    override fun onCreate(): Boolean = true
    override fun query(
        uri: Uri, projection: Array<out String>?, selection: String?,
        selectionArgs: Array<out String>?, sortOrder: String?
    ): Cursor {
        require(uri.authority == FixtureContract.ORACLE_AUTHORITY && uri.path == "/counter")
        val count = requireNotNull(context).getSharedPreferences(
            FixtureContract.COUNTER_PREFS, 0
        ).getInt(FixtureContract.COUNTER_KEY, 0)
        return MatrixCursor(arrayOf("counter")).apply { addRow(arrayOf(count)) }
    }
    override fun getType(uri: Uri): String? = "vnd.android.cursor.item/vnd.androidmcp.fixture.counter"
    override fun insert(uri: Uri, values: ContentValues?): Uri? =
        throw UnsupportedOperationException("Fixture oracle is read-only")
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int =
        throw UnsupportedOperationException("Fixture oracle is read-only")
    override fun update(
        uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?
    ): Int = throw UnsupportedOperationException("Fixture oracle is read-only")
}
