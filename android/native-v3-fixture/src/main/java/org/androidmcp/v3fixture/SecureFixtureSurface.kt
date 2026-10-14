package org.androidmcp.v3fixture

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.view.View

/** Deterministic private-window marker; must NOT appear in an OS screenshot. */
class SecureFixtureSurface(context: Context) : View(context) {
    private val brush = Paint(Paint.ANTI_ALIAS_FLAG)

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        brush.color = FixtureContract.SECURE_MARKER_COLOR
        canvas.drawColor(brush.color)
    }
}
