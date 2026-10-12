/**
 * amazon-cognito-identity-js and @aws-amplify/react-native each vendor an
 * identical copy of JKBigInteger/JKBigDecimal, so linking both pods fails with
 * 7 duplicate Objective-C symbols at the Ld step.
 *
 * Nothing in src/ imports amazon-cognito-identity-js — it is leftover from the
 * pre-Amplify-v6 bootstrap (49d1586a) and auth now goes through aws-amplify v6
 * plus @aws-amplify/react-native. Disabling its native pod keeps the JS package
 * installed while leaving exactly one copy of those symbols in the binary.
 */
module.exports = {
  dependencies: {
    /*
     * ADR-487 D5 — push. Firebase is linked on ANDROID ONLY, deliberately.
     *
     * 1. iOS does not need it. The backend sends to iOS through an SNS APNS
     *    platform application, which takes the raw APNs device token. Firebase
     *    on iOS hands out an FCM token, which that application cannot use.
     * 2. Linking it on iOS would change the iOS build while the Apple step is
     *    parked: v22+ defaults to Swift Package Manager with dynamic
     *    frameworks and needs Xcode 26.2. That belongs with the APNs work, not
     *    hidden inside an Android change.
     *
     * JS that touches these packages must therefore run only on Android —
     * see src/api/pushRegistration.ts, which requires them lazily.
     */
    '@react-native-firebase/app': {
      platforms: {
        ios: null,
      },
    },
    '@react-native-firebase/messaging': {
      platforms: {
        ios: null,
      },
    },
    'amazon-cognito-identity-js': {
      platforms: {
        ios: null,
        android: null,
      },
    },
  },
};
