import React, { useState } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ScrollView, TextInput, Alert, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '@contexts/AuthContext';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

const ROLE_LABELS: Record<string, string> = {
  driver: 'Driver', trainer: 'Trainer', trainee: 'Trainee', walker: 'Walker',
  dispatch: 'Dispatch', management: 'Management', admin: 'Admin',
};
const ROLE_COLORS: Record<string, string> = {
  driver: '#5B4FE8', trainer: '#0FA870', trainee: '#0EA5D8', walker: '#E8820C',
  dispatch: '#8B5CF6', management: '#0FA870', admin: '#DC2626',
};

function getInitials(name: string): string {
  const parts = name.trim().split(' ');
  if (parts.length === 1) return parts[0][0]?.toUpperCase() ?? '?';
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

type EmailStep = 'idle' | 'entering' | 'verifying';

export default function ProfileScreen() {
  // All hooks first — no derived values between them
  const c          = useColors();
  const { user, signOut } = useAuth();
  const navigation = useNavigation<any>();
  const [emailStep,    setEmailStep]    = useState<EmailStep>('idle');
  const [newEmail,     setNewEmail]     = useState('');
  const [code,         setCode]         = useState('');
  const [busy,         setBusy]         = useState(false);
  const [currentEmail, setCurrentEmail] = useState(user?.email ?? '');

  // Derived values after all hooks
  const displayName = user?.firstName ?? user?.email?.split('@')[0] ?? 'Crew Member';
  const primaryRole = ['driver', 'trainer', 'trainee', 'walker', 'dispatch', 'management', 'admin']
    .find(r => user?.groups?.includes(r));
  const roleColor   = primaryRole ? ROLE_COLORS[primaryRole] : c.primary;
  const initials    = getInitials(displayName);

  const requestChange = async () => {
    if (!newEmail.trim() || !newEmail.includes('@')) {
      Alert.alert('Invalid email', 'Enter a valid email address.');
      return;
    }
    setBusy(true);
    try {
      const accessToken = await AsyncStorage.getItem('asheflow_access_token');
      if (!accessToken) throw new Error('Not authenticated. Please sign in again.');
      await apiClient.post('/employees/me/email/request-change', {
        access_token: accessToken,
        new_email: newEmail.trim().toLowerCase(),
      });
      setEmailStep('verifying');
    } catch (e: any) {
      Alert.alert('Error', errorText(e, e.message ?? 'Could not send verification code.'));
    } finally {
      setBusy(false);
    }
  };

  const confirmChange = async () => {
    if (code.trim().length < 6) {
      Alert.alert('Invalid code', 'Enter the 6-digit code sent to your new email.');
      return;
    }
    setBusy(true);
    try {
      const accessToken = await AsyncStorage.getItem('asheflow_access_token');
      if (!accessToken) throw new Error('Not authenticated. Please sign in again.');
      await apiClient.post('/employees/me/email/confirm-change', {
        access_token: accessToken,
        code: code.trim(),
        new_email: newEmail.trim().toLowerCase(),
      });
      setCurrentEmail(newEmail.trim().toLowerCase());
      setEmailStep('idle');
      setNewEmail('');
      setCode('');
      Alert.alert('Done', 'Your email has been updated. Sign in again to refresh your session.', [
        { text: 'Sign out now', onPress: signOut },
        { text: 'Later', style: 'cancel' },
      ]);
    } catch (e: any) {
      Alert.alert('Error', errorText(e, e.message ?? 'Could not verify code.'));
    } finally {
      setBusy(false);
    }
  };

  const cancelEdit = () => {
    setEmailStep('idle');
    setNewEmail('');
    setCode('');
  };

  const s = styles(c);

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      {/* Nav bar */}
      <View style={[s.navBar, { borderBottomColor: c.border }]}>
        <TouchableOpacity onPress={() => navigation.goBack()} hitSlop={{ top: 8, bottom: 8, left: 12, right: 12 }}>
          <Text style={[s.backText, { color: c.primary }]}>‹ Back</Text>
        </TouchableOpacity>
        <Text style={[s.navTitle, { color: c.foreground }]}>Profile</Text>
        <View style={{ width: 56 }} />
      </View>

      <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled">

        {/* Avatar block */}
        <View style={s.avatarSection}>
          <View style={[s.avatarRing, { backgroundColor: roleColor + '18', borderColor: roleColor + '30' }]}>
            <Text style={[s.avatarText, { color: roleColor }]}>{initials}</Text>
          </View>
          <Text style={[s.name, { color: c.foreground }]}>{displayName}</Text>
          {primaryRole && (
            <View style={[s.rolePill, { backgroundColor: roleColor + '15', borderColor: roleColor + '35' }]}>
              <View style={[s.roleDot, { backgroundColor: roleColor }]} />
              <Text style={[s.roleText, { color: roleColor }]}>{ROLE_LABELS[primaryRole]}</Text>
            </View>
          )}
        </View>

        {/* Account info */}
        <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>Account</Text>
        <View style={[s.section, { backgroundColor: c.card, borderColor: c.border }]}>
          {/* Email row — tapping opens edit */}
          {emailStep === 'idle' && (
            <TouchableOpacity
              style={s.row}
              onPress={() => { setNewEmail(currentEmail); setEmailStep('entering'); }}
              activeOpacity={0.7}
            >
              <Text style={[s.rowLabel, { color: c.mutedForeground }]}>Email</Text>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, flex: 1, justifyContent: 'flex-end' }}>
                <Text style={[s.rowValue, { color: c.foreground }]} numberOfLines={1}>{currentEmail}</Text>
                <Text style={[s.editChip, { color: c.primary }]}>Edit</Text>
              </View>
            </TouchableOpacity>
          )}

          {/* Step 1: enter new email */}
          {emailStep === 'entering' && (
            <View style={s.editBlock}>
              <Text style={[s.editLabel, { color: c.foreground }]}>New email address</Text>
              <TextInput
                style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={newEmail}
                onChangeText={setNewEmail}
                placeholder="new@email.com"
                placeholderTextColor={c.mutedForeground}
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
                autoFocus
              />
              <Text style={[s.editHint, { color: c.mutedForeground }]}>
                A verification code will be sent to the new address.
              </Text>
              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelEdit} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={requestChange}
                  disabled={busy}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: busy ? 0.6 : 1 }]}
                >
                  {busy
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={[s.editBtnText, { color: '#fff' }]}>Send Code</Text>
                  }
                </TouchableOpacity>
              </View>
            </View>
          )}

          {/* Step 2: enter verification code */}
          {emailStep === 'verifying' && (
            <View style={s.editBlock}>
              <Text style={[s.editLabel, { color: c.foreground }]}>Verification code</Text>
              <Text style={[s.editHint, { color: c.mutedForeground }]}>
                Enter the 6-digit code sent to {newEmail}
              </Text>
              <TextInput
                style={[s.input, s.codeInput, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={code}
                onChangeText={setCode}
                placeholder="000000"
                placeholderTextColor={c.mutedForeground}
                keyboardType="number-pad"
                maxLength={6}
                autoFocus
              />
              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelEdit} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => { setEmailStep('entering'); setCode(''); }}
                  style={[s.editBtn, { borderColor: c.border }]}
                >
                  <Text style={[s.editBtnText, { color: c.primary }]}>Resend</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={confirmChange}
                  disabled={busy || code.length < 6}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: (busy || code.length < 6) ? 0.5 : 1 }]}
                >
                  {busy
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={[s.editBtnText, { color: '#fff' }]}>Confirm</Text>
                  }
                </TouchableOpacity>
              </View>
            </View>
          )}
        </View>

        {/* Sign out */}
        <TouchableOpacity
          style={[s.signOutBtn, { borderColor: c.danger + '40', backgroundColor: c.danger + '08' }]}
          onPress={signOut}
          activeOpacity={0.75}
        >
          <Text style={[s.signOutText, { color: c.danger }]}>Sign Out</Text>
        </TouchableOpacity>

      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:    { flex: 1, backgroundColor: c.background },
  navBar:  {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm + 2,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  backText:  { fontSize: fontSize.base, fontWeight: fontWeight.medium },
  navTitle:  { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  content:   { padding: spacing.lg, paddingBottom: 60, gap: spacing.md },

  // Avatar
  avatarSection: { alignItems: 'center', paddingVertical: spacing.lg, gap: spacing.sm },
  avatarRing: {
    width: 88, height: 88, borderRadius: 44,
    alignItems: 'center', justifyContent: 'center', borderWidth: 2,
  },
  avatarText: { fontSize: fontSize.xxl, fontWeight: fontWeight.bold },
  name:       { fontSize: fontSize.lg, fontWeight: fontWeight.bold, letterSpacing: -0.3 },
  rolePill:   {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: 5,
    borderRadius: radius.full, borderWidth: 1,
  },
  roleDot:    { width: 7, height: 7, borderRadius: 4 },
  roleText:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  // Section
  sectionLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: -spacing.xs },
  section:   { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden' },

  row: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: spacing.sm + 4, paddingHorizontal: spacing.md,
  },
  rowLabel:  { fontSize: fontSize.sm, color: c.mutedForeground },
  rowValue:  { fontSize: fontSize.sm, fontWeight: fontWeight.medium, flexShrink: 1, marginLeft: spacing.sm },
  editChip:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  // Edit flow
  editBlock: { padding: spacing.md, gap: spacing.sm },
  editLabel: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  editHint:  { fontSize: fontSize.xs, lineHeight: 17 },
  input: {
    borderWidth: 1, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2,
    fontSize: fontSize.base,
  },
  codeInput: { textAlign: 'center', fontSize: fontSize.xl, letterSpacing: 8, fontWeight: fontWeight.bold },
  editActions: { flexDirection: 'row', gap: spacing.xs, marginTop: spacing.xs },
  editBtn: {
    flex: 1, paddingVertical: spacing.sm + 2, borderRadius: radius.md,
    borderWidth: 1, alignItems: 'center', justifyContent: 'center',
  },
  editBtnPrimary: { borderWidth: 0 },
  editBtnText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  // Sign out
  signOutBtn: {
    borderRadius: radius.lg, borderWidth: 1,
    paddingVertical: spacing.md, alignItems: 'center',
  },
  signOutText: { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
});
