package org.androidmcp.v3fixture

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.view.View

class FixtureVisualSurface(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(FixtureContract.MAIN_COLOR)
        val w = width.toFloat()
        val h = height.toFloat()
        paint.color = FixtureContract.RED_COLOR
        canvas.drawRect(w * 0.10f, h * 0.15f, w * 0.34f, h * 0.52f, paint)
        paint.color = FixtureContract.GREEN_COLOR
        canvas.drawRect(w * 0.39f, h * 0.15f, w * 0.63f, h * 0.52f, paint)
        paint.color = FixtureContract.BLUE_COLOR
        canvas.drawRect(w * 0.68f, h * 0.15f, w * 0.92f, h * 0.52f, paint)
    }
}
