import React, { useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '@contexts/AuthContext';
import { useColors, useTheme } from '@contexts/ThemeContext';
import { COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID } from '@env';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

const REGION           = (COGNITO_USER_POOL_ID ?? 'us-east-2_').split('_')[0];
const COGNITO_ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;
const CLIENT_ID        = COGNITO_CLIENT_ID ?? '';

// ── Main component ────────────────────────────────────────────────────────────

export default function MyAccountScreen() {
  const c = useColors();
  const { isDark, toggleTheme, isSystemTheme, useSystemTheme } = useTheme();
  const { user, signOut } = useAuth();
  const s = styles(c);

  const [currentPw,  setCurrentPw]  = useState('');
  const [newPw,      setNewPw]      = useState('');
  const [confirmPw,  setConfirmPw]  = useState('');
  const [saving,     setSaving]     = useState(false);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew,     setShowNew]     = useState(false);

  async function handleChangePassword() {
    if (!newPw.trim() || !currentPw.trim()) {
      Alert.alert('Required', 'Enter your current password and a new password.');
      return;
    }
    if (newPw !== confirmPw) {
      Alert.alert('Mismatch', 'New password and confirmation do not match.');
      return;
    }
    if (newPw.length < 8) {
      Alert.alert('Too short', 'Password must be at least 8 characters.');
      return;
    }

    setSaving(true);
    try {
      const accessToken = await AsyncStorage.getItem('asheflow_access_token');
      if (!accessToken) throw new Error('Not authenticated');

      const res = await fetch(COGNITO_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type':  'application/x-amz-json-1.1',
          'X-Amz-Target':  'AWSCognitoIdentityProviderService.ChangePassword',
        },
        body: JSON.stringify({
          AccessToken:      accessToken,
          PreviousPassword: currentPw,
          ProposedPassword: newPw,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        const errType = data.__type ?? '';
        if (errType === 'NotAuthorizedException') {
          Alert.alert('Wrong password', 'Current password is incorrect.');
        } else if (errType === 'InvalidPasswordException') {
          Alert.alert('Invalid password', data.message ?? 'Password does not meet requirements.');
        } else {
          Alert.alert('Error', data.message ?? 'Could not change password. Try again.');
        }
        return;
      }

      Alert.alert('Password changed', 'Your password has been updated successfully.');
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
    } catch {
      Alert.alert('Error', 'Could not change password. Check your connection and try again.');
    } finally {
      setSaving(false);
    }
  }

  function handleSignOut() {
    Alert.alert('Sign out', 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign out', style: 'destructive', onPress: signOut },
    ]);
  }

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <View style={s.header}>
        <Text style={s.title}>My Account</Text>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>

        {/* Profile info */}
        <View style={[s.infoCard, { backgroundColor: c.surface, borderColor: c.border }]}>
          <View style={[s.avatar, { backgroundColor: c.primary + '22' }]}>
            <Text style={[s.avatarText, { color: c.primary }]}>
              {(user?.firstName ?? '?')[0].toUpperCase()}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[s.name, { color: c.foreground }]}>{user?.firstName ?? '—'}</Text>
            <Text style={[s.username, { color: c.mutedForeground }]}>@{user?.username ?? '—'}</Text>
            <Text style={[s.email, { color: c.mutedForeground }]}>{user?.email ?? '—'}</Text>
            {user?.groups.length ? (
              <View style={s.roleRow}>
                {user.groups.map(g => (
                  <View key={g} style={[s.roleBadge, { backgroundColor: c.primary + '18', borderColor: c.primary }]}>
                    <Text style={[s.roleBadgeText, { color: c.primary }]}>{g}</Text>
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        </View>

        {/* Change password */}
        <Text style={[s.sectionTitle, { color: c.foreground }]}>Change Password</Text>

        <View style={s.fieldGroup}>
          <Text style={[s.label, { color: c.foreground }]}>Current password</Text>
          <View style={[s.inputRow, { borderColor: c.border, backgroundColor: c.surface }]}>
            <TextInput
              style={[s.input, { color: c.foreground }]}
              secureTextEntry={!showCurrent}
              placeholder="Enter current password"
              placeholderTextColor={c.mutedForeground}
              value={currentPw}
              onChangeText={setCurrentPw}
              autoCapitalize="none"
            />
            <TouchableOpacity onPress={() => setShowCurrent(v => !v)} style={s.eyeBtn}>
              <Text style={{ fontSize: 16 }}>{showCurrent ? '🙈' : '👁️'}</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={s.fieldGroup}>
          <Text style={[s.label, { color: c.foreground }]}>New password</Text>
          <View style={[s.inputRow, { borderColor: c.border, backgroundColor: c.surface }]}>
            <TextInput
              style={[s.input, { color: c.foreground }]}
              secureTextEntry={!showNew}
              placeholder="At least 8 characters"
              placeholderTextColor={c.mutedForeground}
              value={newPw}
              onChangeText={setNewPw}
              autoCapitalize="none"
            />
            <TouchableOpacity onPress={() => setShowNew(v => !v)} style={s.eyeBtn}>
              <Text style={{ fontSize: 16 }}>{showNew ? '🙈' : '👁️'}</Text>
            </TouchableOpacity>
          </View>
        </View>

        <View style={s.fieldGroup}>
          <Text style={[s.label, { color: c.foreground }]}>Confirm new password</Text>
          <View style={[s.inputRow, {
            borderColor: confirmPw && confirmPw !== newPw ? '#EF4444' : c.border,
            backgroundColor: c.surface,
          }]}>
            <TextInput
              style={[s.input, { color: c.foreground }]}
              secureTextEntry
              placeholder="Re-enter new password"
              placeholderTextColor={c.mutedForeground}
              value={confirmPw}
              onChangeText={setConfirmPw}
              autoCapitalize="none"
            />
          </View>
          {confirmPw.length > 0 && confirmPw !== newPw && (
            <Text style={{ color: '#EF4444', fontSize: fontSize.xs, marginTop: 2 }}>Passwords do not match</Text>
          )}
        </View>

        <TouchableOpacity
          style={[s.saveBtn, { backgroundColor: c.primary, opacity: saving ? 0.7 : 1 }]}
          onPress={handleChangePassword}
          disabled={saving}
          activeOpacity={0.8}
        >
          {saving
            ? <ActivityIndicator size="small" color="#fff" />
            : <Text style={s.saveBtnText}>Update Password</Text>
          }
        </TouchableOpacity>

        {/* Appearance */}
        <View style={[s.divider, { backgroundColor: c.border }]} />
        <Text style={[s.sectionTitle, { color: c.foreground }]}>Appearance</Text>

        <View style={[s.themeRow, { backgroundColor: c.surface, borderColor: c.border }]}>
          <Text style={[s.themeLabel, { color: c.foreground }]}>
            {isDark ? '🌙 Dark mode' : '☀️ Light mode'}
          </Text>
          <TouchableOpacity
            style={[s.themeToggle, { backgroundColor: isDark ? c.primary : c.border }]}
            onPress={toggleTheme}
            activeOpacity={0.8}
          >
            <View style={[s.themeKnob, { transform: [{ translateX: isDark ? 20 : 2 }] }]} />
          </TouchableOpacity>
        </View>

        {!isSystemTheme && (
          <TouchableOpacity onPress={useSystemTheme}>
            <Text style={{ color: c.mutedForeground, fontSize: fontSize.xs, textAlign: 'center', marginTop: -spacing.xs }}>
              Use system setting
            </Text>
          </TouchableOpacity>
        )}

        {/* Sign out */}
        <View style={[s.divider, { backgroundColor: c.border }]} />

        <TouchableOpacity
          style={[s.signOutBtn, { borderColor: '#EF4444' }]}
          onPress={handleSignOut}
          activeOpacity={0.8}
        >
          <Text style={[s.signOutText, { color: '#EF4444' }]}>Sign out</Text>
        </TouchableOpacity>

        <View style={{ height: spacing.xl }} />
      </ScrollView>
    </SafeAreaView>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:         { flex: 1, backgroundColor: c.background },
  header:       { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.xs, borderBottomWidth: 1, borderBottomColor: c.border },
  title:        { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  sectionTitle: { fontSize: fontSize.base, fontWeight: fontWeight.semibold },

  infoCard:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' },
  avatar:       { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  avatarText:   { fontSize: 24, fontWeight: fontWeight.bold },
  name:         { fontSize: fontSize.base, fontWeight: fontWeight.bold },
  username:     { fontSize: fontSize.sm },
  email:        { fontSize: fontSize.xs, marginTop: 2 },
  roleRow:      { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.xs },
  roleBadge:    { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.xs + 2, paddingVertical: 2 },
  roleBadgeText:{ fontSize: 10, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },

  fieldGroup:   { gap: spacing.xs },
  label:        { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  inputRow:     { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.sm },
  input:        { flex: 1, paddingVertical: spacing.sm, fontSize: fontSize.sm },
  eyeBtn:       { paddingLeft: spacing.xs },

  saveBtn:      { borderRadius: radius.md, padding: spacing.md, alignItems: 'center' },
  saveBtnText:  { color: '#fff', fontSize: fontSize.base, fontWeight: fontWeight.bold },

  divider:      { height: 1, marginVertical: spacing.xs },
  signOutBtn:   { borderWidth: 1.5, borderRadius: radius.md, padding: spacing.md, alignItems: 'center' },
  signOutText:  { fontSize: fontSize.base, fontWeight: fontWeight.semibold },

  themeRow:     { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  themeLabel:   { fontSize: fontSize.base, fontWeight: fontWeight.medium },
  themeToggle:  { width: 44, height: 26, borderRadius: 13, justifyContent: 'center' },
  themeKnob:    { width: 22, height: 22, borderRadius: 11, backgroundColor: '#fff', shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 2, elevation: 2 },
});
