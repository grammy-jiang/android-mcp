package org.androidmcp.nativeapp

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

/**
 * User-initiated and foreground-only preview; stops when not visible.
 * No boot receiver, background service, Accessibility or automatic restart.
 */
class NativeMcpActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val gateway = LocalMcpGateway()
    private val generation = AtomicInteger(0)
    private lateinit var status: TextView
    private lateinit var startButton: Button
    private lateinit var backgroundPreviewButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (24 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        content.addView(TextView(this).apply {
            text = "Android MCP Native — local preview"
            textSize = 21f
        })
        status = TextView(this).apply {
            text = "Stopped. Read-only; no Root, UI control or remote listener."
            textSize = 15f
        }
        content.addView(status)
        startButton = Button(this).apply {
            text = "Start local read-only MCP"
            setOnClickListener { startLocalMcp() }
        }
        content.addView(startButton)
        backgroundPreviewButton = Button(this).apply {
            text = "Open persistent service preview"
            setOnClickListener {
                // The Activity listener stops onStop before this screen can
                // launch a separately user-controlled foreground service.
                startActivity(Intent(this@NativeMcpActivity, BackgroundMcpActivity::class.java))
            }
        }
        content.addView(backgroundPreviewButton)
        setContentView(content)
    }

    private fun startLocalMcp() {
        val ticket = generation.incrementAndGet()
        startButton.isEnabled = false
        backgroundPreviewButton.isEnabled = false
        status.text = "Starting local-only MCP..."
        worker.execute {
            try {
                if (generation.get() != ticket) return@execute
                gateway.start()
                if (generation.get() != ticket) {
                    gateway.stop()
                    return@execute
                }
                runOnUiThread {
                    if (generation.get() == ticket) {
                        status.text = "Running on 127.0.0.1:38765/mcp — local status only."
                    }
                }
            } catch (_: Exception) {
                gateway.stop()
                runOnUiThread {
                    if (generation.get() == ticket) {
                        status.text = "Could not start local MCP listener."
                        startButton.isEnabled = true
                        backgroundPreviewButton.isEnabled = true
                    }
                }
            }
        }
    }

    private fun stopLocalMcp() {
        generation.incrementAndGet()
        worker.execute { gateway.stop() }
        status.text = "Stopped while app is not visible."
        startButton.isEnabled = true
        backgroundPreviewButton.isEnabled = true
    }

    override fun onStop() {
        stopLocalMcp()
        super.onStop()
    }

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }
}
