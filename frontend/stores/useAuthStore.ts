"use client";

import { create } from "zustand";

import { api, readToken, writeToken } from "@/lib/api";
import type { TokenResponse, User } from "@/lib/types";

interface AuthState {
  user: User | null;
  status: "idle" | "loading" | "ready";
  /**
   * True once the initial session check has finished, and never false again.
   *
   * Distinct from `status` on purpose: `status` also goes to "loading" during a
   * login, and gating the whole app on that would unmount the login form
   * mid-submit.
   */
  hydrated: boolean;
  error: string | null;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  devLogin: () => Promise<void>;
  exchangeGoogleCode: (code: string) => Promise<void>;
  acceptToken: (result: TokenResponse) => void;
  logout: () => void;
  /**
   * Re-read the account HUD (total EXP, account level, streak) after a grade.
   *
   * Deliberately a refetch rather than a client-side patch. The account level
   * curve lives in `app/domain/exp.py`; there is no shared codegen, so any
   * attempt to advance the HUD locally means reimplementing that curve in
   * TypeScript and letting the two drift.
   */
  refreshUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  status: "idle",
  hydrated: false,
  error: null,

  hydrate: async () => {
    set({ status: "loading" });
    try {
      let user: User;
      if (readToken()) {
        try {
          user = await api.me();
        } catch {
          const refreshed = await api.refresh();
          writeToken(refreshed.access_token);
          user = refreshed.user;
        }
      } else {
        const refreshed = await api.refresh();
        writeToken(refreshed.access_token);
        user = refreshed.user;
      }
      set({ user, status: "ready", hydrated: true, error: null });
    } catch {
      // No access token or refresh cookie remains valid; clear the client copy
      // rather than looping on every navigation.
      writeToken(null);
      set({ user: null, status: "ready", hydrated: true });
    }
  },

  login: async (email, password) => {
    set({ status: "loading", error: null });
    try {
      const result = await api.login(email, password);
      writeToken(result.access_token);
      set({ user: result.user, status: "ready" });
    } catch (error) {
      set({ status: "ready", error: (error as Error).message });
      throw error;
    }
  },

  register: async (email, password, displayName) => {
    set({ status: "loading", error: null });
    try {
      const result = await api.register(email, password, displayName);
      writeToken(result.access_token);
      set({ user: result.user, status: "ready" });
    } catch (error) {
      set({ status: "ready", error: (error as Error).message });
      throw error;
    }
  },

  acceptToken: (result) => {
    writeToken(result.access_token);
    set({ user: result.user, status: "ready", hydrated: true, error: null });
  },

  exchangeGoogleCode: async (code) => {
    set({ status: "loading", error: null });
    try {
      const result = await api.exchangeGoogleCode(code);
      writeToken(result.access_token);
      set({ user: result.user, status: "ready" });
    } catch (error) {
      set({ status: "ready", error: (error as Error).message });
      throw error;
    }
  },

  devLogin: async () => {
    set({ status: "loading", error: null });
    try {
      const result = await api.devLogin();
      writeToken(result.access_token);
      set({ user: result.user, status: "ready" });
    } catch (error) {
      set({
        status: "ready",
        // The seed instruction that used to be here was wrong as of the
        // endpoint provisioning its own user: a missing dev user is no longer
        // a reason for this to fail, so the only remaining cause is the route
        // not being registered.
        error: "Dev login is unavailable. Start the API with DEV_AUTH_ENABLED=true.",
      });
      throw error;
    }
  },

  logout: () => {
    void api.logout().catch(() => undefined);
    writeToken(null);
    set({ user: null, error: null });
  },

  refreshUser: async () => {
    try {
      set({ user: await api.me() });
    } catch {
      // A failed HUD refresh must never blank the HUD or interrupt the drill;
      // the existing values stay until the next successful read.
    }
  },
}));
