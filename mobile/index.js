/**
 * @format
 */

// Amplify must be configured before ANY auth call, so this import comes first
// and is a side effect, not a value (ADR-362).
import '@aws-amplify/react-native';
import './src/amplify';

import { AppRegistry, Platform } from 'react-native';
import App from './App';
import { name as appName } from './app.json';

// ADR-519 D8: FCM wakes a killed app for every push and looks for this
// headless task; without one it warns "No task registered for key
// ReactNativeFirebaseMessagingHeadlessTask". There is nothing to do in the
// background: the system shows the notification, and the app refreshes from
// the server when it opens. Android only, required lazily like
// api/pushRegistration.ts, so iOS never evaluates the package.
if (Platform.OS === 'android') {
  try {
    const { getMessaging, setBackgroundMessageHandler } = require('@react-native-firebase/messaging');
    setBackgroundMessageHandler(getMessaging(), async () => {});
  } catch {
    // Push is additive; a missing Firebase config must not stop the app.
  }
}

AppRegistry.registerComponent(appName, () => App);
