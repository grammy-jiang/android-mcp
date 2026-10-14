package org.androidmcp.v3fixture

import android.database.Cursor
import android.database.MatrixCursor
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.provider.DocumentsProvider
import java.io.FileNotFoundException

/** Only a single deterministic read-only document. Scoped SAF grant required. */
class FixtureDocumentsProvider : DocumentsProvider() {
    override fun onCreate(): Boolean = true
    override fun queryRoots(projection: Array<out String>?): Cursor {
        val columns = projection ?: arrayOf(
            DocumentsContract.Root.COLUMN_ROOT_ID,
            DocumentsContract.Root.COLUMN_DOCUMENT_ID,
            DocumentsContract.Root.COLUMN_TITLE,
            DocumentsContract.Root.COLUMN_FLAGS,
            DocumentsContract.Root.COLUMN_MIME_TYPES,
        )
        return MatrixCursor(columns).apply {
            newRow().apply {
                add(DocumentsContract.Root.COLUMN_ROOT_ID, FixtureContract.ROOT_ID)
                add(DocumentsContract.Root.COLUMN_DOCUMENT_ID, FixtureContract.ROOT_ID)
                add(DocumentsContract.Root.COLUMN_TITLE, "MCP V3 Fixture Docs")
                add(DocumentsContract.Root.COLUMN_FLAGS, 0)
                add(DocumentsContract.Root.COLUMN_MIME_TYPES, "text/plain")
            }
        }
    }

    override fun queryDocument(documentId: String, projection: Array<out String>?): Cursor =
        MatrixCursor(projection ?: docProjection()).apply { include(documentId) }

    override fun queryChildDocuments(
        parentDocumentId: String, projection: Array<out String>?, sortOrder: String?
    ): Cursor = MatrixCursor(projection ?: docProjection()).apply {
        if (parentDocumentId != FixtureContract.ROOT_ID) throw FileNotFoundException()
        include(FixtureContract.KNOWN_ID)
    }

    private fun docProjection() = arrayOf(
        DocumentsContract.Document.COLUMN_DOCUMENT_ID,
        DocumentsContract.Document.COLUMN_DISPLAY_NAME,
        DocumentsContract.Document.COLUMN_MIME_TYPE,
        DocumentsContract.Document.COLUMN_SIZE,
        DocumentsContract.Document.COLUMN_FLAGS,
    )

    private fun MatrixCursor.include(id: String) {
        if (id !in setOf(FixtureContract.ROOT_ID, FixtureContract.KNOWN_ID)) {
            throw FileNotFoundException("Unknown fixture id")
        }
        newRow().apply {
            add(DocumentsContract.Document.COLUMN_DOCUMENT_ID, id)
            add(
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                if (id == FixtureContract.KNOWN_ID) FixtureContract.FILE_NAME else "MCP V3 Fixture"
            )
            add(
                DocumentsContract.Document.COLUMN_MIME_TYPE,
                if (id == FixtureContract.ROOT_ID)
                    DocumentsContract.Document.MIME_TYPE_DIR else "text/plain"
            )
            add(DocumentsContract.Document.COLUMN_SIZE,
                if (id == FixtureContract.ROOT_ID) 0 else FixtureContract.knownBytes().size)
            add(DocumentsContract.Document.COLUMN_FLAGS, 0)
        }
    }

    override fun openDocument(
        documentId: String, mode: String, signal: CancellationSignal?
    ): ParcelFileDescriptor {
        signal?.throwIfCanceled()
        if (documentId != FixtureContract.KNOWN_ID || mode != "r") {
            throw FileNotFoundException("Fixture is read-only or id is invalid")
        }
        val (read, write) = ParcelFileDescriptor.createPipe()
        ParcelFileDescriptor.AutoCloseOutputStream(write).use {
            it.write(FixtureContract.knownBytes())
        }
        return read
    }
}
