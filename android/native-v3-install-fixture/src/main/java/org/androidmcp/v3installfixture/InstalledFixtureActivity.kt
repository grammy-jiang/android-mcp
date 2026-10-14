package org.androidmcp.v3installfixture

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

class InstalledFixtureActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(TextView(this).apply {
            text = "MCP V3 Installer Target: installed with user confirmation required"
            textSize = 20f
        })
    }
}
