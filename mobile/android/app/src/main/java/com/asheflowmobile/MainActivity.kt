package com.asheflowmobile

import android.content.Intent
import android.os.Bundle
import com.swmansion.rnscreens.fragment.restoration.RNScreensFragmentFactory
import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate

class MainActivity : ReactActivity() {

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "AsheFlowMobile"

  /**
   * react-native-screens: screen fragments must never be restored. Without this,
   * Android relaunching the activity from saved state (tapping a push after the
   * process was killed, ADR-519 D8) crashed on start with
   * "Screen fragments should never be restored" (ScreenStackFragment). The
   * factory is the library's documented fix (README, Android setup).
   */
  override fun onCreate(savedInstanceState: Bundle?) {
    supportFragmentManager.fragmentFactory = RNScreensFragmentFactory()
    super.onCreate(savedInstanceState)
  }

  /**
   * Keep the newest intent as THE intent (ADR-519 D8). When Android has killed
   * the process but kept the task, tapping a push recreates this activity from
   * its ORIGINAL launcher intent and delivers the push's intent here, before
   * React Native has created the messaging module that would listen for it.
   * `getInitialNotification` then reads `getIntent()`, which without this
   * still returns the old launcher intent, and the tap opens Home. Measured on
   * the emulator: the running activity's intent had no extras.
   */
  override fun onNewIntent(intent: Intent) {
    super.onNewIntent(intent)
    setIntent(intent)
  }

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
  override fun createReactActivityDelegate(): ReactActivityDelegate =
      DefaultReactActivityDelegate(this, mainComponentName, fabricEnabled)
}
