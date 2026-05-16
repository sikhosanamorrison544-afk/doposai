package com.pos.mobile.ui

import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updatePadding
import kotlin.math.max

/** Edge-to-edge safe area: status bar, notch, gesture nav, keyboard (IME). */
fun AppCompatActivity.applyEdgeToEdgeInsets(root: View) {
    WindowCompat.setDecorFitsSystemWindows(window, false)
    ViewCompat.setOnApplyWindowInsetsListener(root) { v, windowInsets ->
        val bars = windowInsets.getInsets(
            WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
        )
        val ime = windowInsets.getInsets(WindowInsetsCompat.Type.ime())
        v.updatePadding(bars.left, bars.top, bars.right, max(bars.bottom, ime.bottom))
        windowInsets
    }
}
