module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    [
      'module-resolver',
      {
        root: ['./src'],
        alias: {
          '@api':        './src/api',
          '@contexts':   './src/contexts',
          '@navigation': './src/navigation',
          '@screens':    './src/screens',
          '@components': './src/components',
          '@hooks':      './src/hooks',
          '@theme':      './src/theme',
          '@assets':     './src/assets',
        },
      },
    ],
    // Injects .env variables into process.env at bundle time
    ['module:react-native-dotenv', {
      envName:    'APP_ENV',
      moduleName: '@env',
      path:       '.env',
      safe:       false,
      allowUndefined: true,
    }],
  ],
};
