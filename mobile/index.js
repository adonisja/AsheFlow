/**
 * @format
 */

// Amplify must be configured before ANY auth call, so this import comes first
// and is a side effect, not a value (ADR-362).
import '@aws-amplify/react-native';
import './src/amplify';

import { AppRegistry } from 'react-native';
import App from './App';
import { name as appName } from './app.json';

AppRegistry.registerComponent(appName, () => App);
