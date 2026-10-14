package org.androidmcp.v3fixture

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.WindowInsets
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class FixtureActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // API 35+ enforces edge-to-edge for targetSdk >= 35. Without the
        // actual system-bar insets, Android 16 delivers visual but not touch
        // access to the counter button underneath the status bar.
        val parent = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
        }
        val name = TextView(this).apply { text = "Android MCP V3 Known Pixels Fixture" }
        val counter = TextView(this).apply {
            id = FixtureContract.TEXT_ID
            text = "Fixture counter: " + count()
        }
        val button = Button(this).apply {
            id = FixtureContract.BUTTON_ID
            text = "Increment fixture counter"
            contentDescription = "android-mcp-v3-increment-counter"
            setOnClickListener {
                val prefs = getSharedPreferences(FixtureContract.COUNTER_PREFS, MODE_PRIVATE)
                val next = prefs.getInt(FixtureContract.COUNTER_KEY, 0) + 1
                check(prefs.edit().putInt(FixtureContract.COUNTER_KEY, next).commit())
                counter.text = "Fixture counter: " + count()
            }
        }
        parent.addView(name)
        parent.addView(counter)
        parent.addView(button)
        parent.addView(Button(this).apply {
            id = FixtureContract.SECURE_OPEN_BUTTON_ID
            text = "Open synthetic secure test window"
            contentDescription = "android-mcp-v3-open-secure-fixture"
            setOnClickListener {
                startActivity(Intent(this@FixtureActivity, SecureFixtureActivity::class.java))
            }
        })
        parent.addView(FixtureVisualSurface(this).apply {
            id = FixtureContract.SURFACE_ID
        }, LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f
        ))
        setContentView(parent)
    }

    private fun count(): Int = getSharedPreferences(
        FixtureContract.COUNTER_PREFS, MODE_PRIVATE
    ).getInt(FixtureContract.COUNTER_KEY, 0)
}
