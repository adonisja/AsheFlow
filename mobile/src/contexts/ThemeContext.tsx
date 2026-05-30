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
  toggleTheme: () => void;
  isSystemTheme: boolean;
  useSystemTheme: () => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  scheme: 'light',
  isDark: false,
  colors: lightColors,
  toggleTheme: () => {},
  isSystemTheme: true,
  useSystemTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const deviceScheme = useColorScheme();
  // null = follow system, 'light'/'dark' = manual override
  const [override, setOverride] = useState<ColorScheme | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY).then(val => {
      if (val === 'light' || val === 'dark') setOverride(val);
      setLoaded(true);
    });
  }, []);

  const activeScheme: ColorScheme = override ?? (deviceScheme === 'dark' ? 'dark' : 'light');
  const isDark = activeScheme === 'dark';

  const toggleTheme = useCallback(() => {
    const next: ColorScheme = isDark ? 'light' : 'dark';
    setOverride(next);
    AsyncStorage.setItem(STORAGE_KEY, next);
  }, [isDark]);

  const useSystemTheme = useCallback(() => {
    setOverride(null);
    AsyncStorage.removeItem(STORAGE_KEY);
  }, []);

  const value = useMemo<ThemeContextValue>(() => ({
    scheme: activeScheme,
    isDark,
    colors: isDark ? darkColors : lightColors,
    toggleTheme,
    isSystemTheme: override === null,
    useSystemTheme,
  }), [activeScheme, isDark, toggleTheme, useSystemTheme, override]);

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
