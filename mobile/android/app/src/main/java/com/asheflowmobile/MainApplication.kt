package com.asheflowmobile

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.facebook.react.PackageList
import com.facebook.react.ReactApplication
import com.facebook.react.ReactHost
import com.facebook.react.ReactNativeApplicationEntryPoint.loadReactNative
import com.facebook.react.defaults.DefaultReactHost.getDefaultReactHost

class MainApplication : Application(), ReactApplication {

  override val reactHost: ReactHost by lazy {
    getDefaultReactHost(
      context = applicationContext,
      packageList =
        PackageList(this).packages.apply {
          // Packages that cannot be autolinked yet can be added manually here, for example:
          // add(MyReactNativePackage())
        },
    )
  }

  override fun onCreate() {
    super.onCreate()
    createPushChannel()
    loadReactNative(this)
  }

  /**
   * The channel push notifications are shown in (ADR-487 D5).
   *
   * Without our own channel FCM uses its fallback, labelled "Miscellaneous" in
   * system settings. A walker who mutes "Miscellaneous" mutes injury alerts
   * without knowing it, so the channel is named for what it carries.
   *
   * The id is a CONTRACT with the backend: push_delivery.ANDROID_CHANNEL_ID
   * sends `android_channel_id` = this value, and mobile/firebase.json names it as
   * FCM's default (React Native Firebase writes that into its own manifest). test_adr487_d5_android_channel checks all three agree. A channel
   * id cannot be renamed once shipped — Android keeps the user's settings
   * against the old id — so it is deliberately plain.
   *
   * Created at every launch: createNotificationChannel is idempotent and keeps
   * whatever importance the user has since changed.
   */
  private fun createPushChannel() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
    val channel = NotificationChannel(
      PUSH_CHANNEL_ID,
      "Alerts",
      NotificationManager.IMPORTANCE_HIGH,
    ).apply {
      description = "Assignments, help requests and other notices that need you"
    }
    getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
  }

  companion object {
    const val PUSH_CHANNEL_ID = "alerts"
  }
}
