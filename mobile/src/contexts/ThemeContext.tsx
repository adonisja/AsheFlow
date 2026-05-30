import React, { createContext, useContext, useMemo } from 'react';
import { useColorScheme } from 'react-native';
import { lightColors, darkColors, type ThemeColors } from '@theme/index';

type ColorScheme = 'light' | 'dark';

type ThemeContextValue = {
  scheme: ColorScheme;
  isDark: boolean;
  colors: ThemeColors;
};

const ThemeContext = createContext<ThemeContextValue>({
  scheme: 'light',
  isDark: false,
  colors: lightColors,
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const deviceScheme = useColorScheme();
  const isDark = deviceScheme === 'dark';

  const value = useMemo<ThemeContextValue>(() => ({
    scheme: isDark ? 'dark' : 'light',
    isDark,
    colors: isDark ? darkColors : lightColors,
  }), [isDark]);

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

// Primary hook — use this everywhere instead of the inline pattern:
//   const scheme = useColorScheme();
//   const c = scheme === 'dark' ? darkColors : lightColors;
export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

// Convenience alias — most components only need the color map
export function useColors(): ThemeColors {
  return useContext(ThemeContext).colors;
}
