package org.androidmcp.v3fixture

import android.app.Activity
import android.os.Bundle
import android.text.InputType
import android.view.WindowManager
import android.view.View
import android.view.WindowInsets
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Synthetic confidential-window Android test target. No real user secrets.
 * Baseline intentionally lacks secure flag/password classification for
 * genuine on-device behavioral RED.
 */
class SecureFixtureActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Set protection before building the content: no unprotected first frame.
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
        }
        val label = TextView(this).apply {
            text = "MCP V3 Synthetic Secure Window"
        }
        val password = EditText(this).apply {
            id = FixtureContract.SECURE_PASSWORD_ID
            contentDescription = "android-mcp-v3-synthetic-password"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        val visible = SecureFixtureSurface(this).apply {
            id = FixtureContract.SECURE_SURFACE_ID
        }
        root.addView(label)
        root.addView(password)
        root.addView(
            visible,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
        )
        setContentView(root)
    }
}
