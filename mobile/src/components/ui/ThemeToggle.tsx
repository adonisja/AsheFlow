import React from 'react';
import { TouchableOpacity, Text, StyleSheet } from 'react-native';
import { useTheme } from '@contexts/ThemeContext';
import { radius, fontSize, hitSlop } from '@theme/index';

/**
 * Quick light/dark toggle for the app header (ADR-207). Taps flip between light
 * and dark directly (a manual pick, which also stops following the OS schedule —
 * the remedy when the device's auto dark-theme timing is off). The full
 * System / Light / Dark control still lives in Account.
 */
export default function ThemeToggle() {
  const { isDark, colors: c, setTheme } = useTheme();
  return (
    <TouchableOpacity
      onPress={() => setTheme(isDark ? 'light' : 'dark')}
      hitSlop={hitSlop}
      accessibilityRole="button"
      accessibilityLabel={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      style={[styles.btn, { backgroundColor: c.surfaceMuted, borderColor: c.border }]}
    >
      <Text style={[styles.icon, { color: c.foreground }]}>{isDark ? '☀️' : '🌙'}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  btn:  { width: 40, height: 40, borderRadius: radius.full, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  icon: { fontSize: fontSize.md },
});
