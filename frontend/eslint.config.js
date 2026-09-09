import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      // A `const` arrow function used above its declaration is a temporal dead
      // zone error: it compiles, `tsc` is silent, and it throws the first time
      // that path runs. It shipped twice in one day — `beginEntry` called from
      // `addOv` (86b9f5c3) and `send` called from `act` (64a5f935) — each time
      // reaching a real button before being caught by reading declaration
      // order by hand.
      //
      // `functions: false` keeps hoisted `function` declarations legal, which
      // is a normal and safe style. `variables: true` is the half that matters:
      // consts are NOT hoisted, so using one early is always a bug.
      // WARN, not error, and the distinction is measured rather than assumed:
      // switching it on flagged 36 places, of which 34 are a `useCallback` or a
      // setter referenced inside ANOTHER callback. Those run after the
      // component function has fully evaluated, so they are safe today — but
      // they are the same shape as the two that were not, and the rule cannot
      // tell them apart.
      //
      // At `error` this would block every build on 34 non-bugs, and the fix
      // people would reach for is a blanket disable. A warning surfaces the new
      // one in a diff without that pressure. Raise it to `error` if the
      // existing 34 are ever reordered.
      '@typescript-eslint/no-use-before-define': [
        'warn',
        { functions: false, variables: true, typedefs: false, enums: false },
      ],
    },
  },
])
