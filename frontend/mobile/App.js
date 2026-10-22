/**
 * Subh AI mobile client.
 *
 * Shares frontend/shared/api.js with the web app, so request shapes and error
 * semantics are identical across platforms. Only the view layer differs.
 *
 * Not built in this environment: it needs an Android SDK or Xcode. Run it with
 * `npx expo start` from this directory.
 *
 * Note on apiBase: an Android emulator reaches the host machine at 10.0.2.2 -
 * localhost inside the emulator is the emulator itself.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import Constants from "expo-constants";
import { StatusBar } from "expo-status-bar";

import { createClient } from "../shared/api.js";

const API_BASE = Constants.expoConfig?.extra?.apiBase ?? "http://10.0.2.2:8000";
const SESSION_ID = "mobile";

export default function App() {
  const [api] = useState(() => createClient({ baseUrl: API_BASE }));
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);
  const [problem, setProblem] = useState(null);
  const listRef = useRef(null);

  useEffect(() => {
    api
      .status()
      .then((status) =>
        setProblem(status.configured ? null : "No model configured on the server.")
      )
      .catch((error) => setProblem(error.message));
  }, [api]);

  const push = useCallback((message) => {
    setMessages((current) => [...current, message]);
  }, []);

  const handle = useCallback(
    (result) => {
      if (result.status === "awaiting_confirmation") {
        setPending(result);
        push({ role: "assistant", text: "I need your approval before running that." });
      } else {
        setPending(null);
        push({
          role: "assistant",
          text: result.answer || result.question || result.detail || result.status,
        });
      }
    },
    [push]
  );

  async function send() {
    const message = draft.trim();
    if (!message || busy) return;
    setDraft("");
    push({ role: "user", text: message });
    setBusy(true);
    try {
      handle(await api.run(message, SESSION_ID));
    } catch (error) {
      push({ role: "system", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  async function decide(approve) {
    setBusy(true);
    try {
      if (approve) await api.approve(pending.confirmation_token);
      else await api.deny(pending.confirmation_token);
      handle(await api.resume(SESSION_ID));
    } catch (error) {
      push({ role: "system", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.screen}>
      <StatusBar style="light" />
      <View style={styles.header}>
        <Text style={styles.brand}>Subh AI</Text>
        {busy ? <ActivityIndicator color="#6c8cff" /> : null}
      </View>

      {problem ? <Text style={styles.banner}>{problem}</Text> : null}

      <FlatList
        ref={listRef}
        data={messages}
        style={styles.list}
        keyExtractor={(_, index) => String(index)}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.role === "user" ? styles.user : styles.assistant]}>
            <Text style={styles.bubbleText}>{item.text}</Text>
          </View>
        )}
        ListEmptyComponent={<Text style={styles.empty}>Ask Subh AI something to get started.</Text>}
      />

      {pending ? (
        <View style={styles.approval}>
          <Text style={styles.approvalTitle}>Approval needed</Text>
          <Text style={styles.approvalBody}>
            {pending.pending_call?.arguments?.command ?? pending.pending_call?.tool}
          </Text>
          <View style={styles.row}>
            <Pressable style={[styles.button, styles.primary]} onPress={() => decide(true)}>
              <Text style={styles.buttonText}>Approve</Text>
            </Pressable>
            <Pressable style={styles.button} onPress={() => decide(false)}>
              <Text style={styles.buttonText}>Deny</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.composer}>
          <TextInput
            style={styles.input}
            value={draft}
            onChangeText={setDraft}
            placeholder="Message Subh AI..."
            placeholderTextColor="#8b9ac4"
            onSubmitEditing={send}
          />
          <Pressable style={[styles.button, styles.primary]} onPress={send} disabled={busy}>
            <Text style={styles.buttonText}>Send</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: "#0b0f1a" },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#253050",
  },
  brand: { color: "#e8edf9", fontSize: 18, fontWeight: "700" },
  banner: { color: "#f5a623", padding: 12, fontSize: 13 },
  list: { flex: 1, paddingHorizontal: 12 },
  bubble: { marginVertical: 5, padding: 11, borderRadius: 14, maxWidth: "88%" },
  user: { alignSelf: "flex-end", backgroundColor: "#6c8cff" },
  assistant: {
    alignSelf: "flex-start",
    backgroundColor: "#121829",
    borderWidth: 1,
    borderColor: "#253050",
  },
  bubbleText: { color: "#e8edf9", fontSize: 15 },
  empty: { color: "#8b9ac4", textAlign: "center", marginTop: 48 },
  approval: {
    margin: 12,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#f5a623",
    backgroundColor: "rgba(245,166,35,0.08)",
  },
  approvalTitle: { color: "#f5a623", fontWeight: "700", marginBottom: 6 },
  approvalBody: { color: "#e8edf9", fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace" },
  row: { flexDirection: "row", gap: 8, marginTop: 10 },
  composer: {
    flexDirection: "row",
    gap: 8,
    padding: 12,
    borderTopWidth: 1,
    borderTopColor: "#253050",
  },
  input: {
    flex: 1,
    color: "#e8edf9",
    backgroundColor: "#1a2238",
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
  },
  button: {
    paddingHorizontal: 16,
    justifyContent: "center",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#253050",
  },
  primary: { backgroundColor: "#6c8cff", borderColor: "#6c8cff" },
  buttonText: { color: "#fff", fontWeight: "600" },
});
