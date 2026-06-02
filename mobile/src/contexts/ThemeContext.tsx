import React, { createContext, useContext, useMemo, useState, useEffect, useCallback } from 'react';
import { useColorScheme } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { lightColors, darkColors, type ThemeColors } from '@theme/index';

const STORAGE_KEY = 'asheflow_theme_override';

type ColorScheme = 'light' | 'dark';

type ThemeContextValue = {
  scheme: ColorScheme;
  isDark: boolean;
  colors: ThemeColors;
  // Set an explicit override; pass null to revert to system
  setTheme: (scheme: ColorScheme | null) => void;
  isSystemTheme: boolean;
  // Convenience flip — kept for any callers that still use it
  toggleTheme: () => void;
  useSystemTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  scheme: 'light',
  isDark: false,
  colors: lightColors,
  setTheme: () => {},
  toggleTheme: () => {},
  isSystemTheme: true,
  useSystemTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const deviceScheme = useColorScheme();
  const [override, setOverride] = useState<ColorScheme | null>(null);
  const [loaded,   setLoaded]   = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY).then(val => {
      if (val === 'light' || val === 'dark') setOverride(val);
      setLoaded(true);
    });
  }, []);

  const activeScheme: ColorScheme = override ?? (deviceScheme === 'dark' ? 'dark' : 'light');
  const isDark = activeScheme === 'dark';

  const setTheme = useCallback((scheme: ColorScheme | null) => {
    setOverride(scheme);
    if (scheme === null) {
      AsyncStorage.removeItem(STORAGE_KEY);
    } else {
      AsyncStorage.setItem(STORAGE_KEY, scheme);
    }
  }, []);

  const toggleTheme    = useCallback(() => setTheme(isDark ? 'light' : 'dark'), [isDark, setTheme]);
  const useSystemTheme = useCallback(() => setTheme(null), [setTheme]);

  const value = useMemo<ThemeContextValue>(() => ({
    scheme: activeScheme,
    isDark,
    colors: isDark ? darkColors : lightColors,
    setTheme,
    toggleTheme,
    isSystemTheme: override === null,
    useSystemTheme,
  }), [activeScheme, isDark, setTheme, toggleTheme, useSystemTheme, override]);

  if (!loaded) return null;

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

export function useColors(): ThemeColors {
  return useContext(ThemeContext).colors;
}
