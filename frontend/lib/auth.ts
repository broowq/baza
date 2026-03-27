"use client";

const TOKEN_KEY = "lid_access_token";
const ORG_KEY = "lid_org_id";

export function setToken(token: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function getToken() {
  return typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY);
}

export function clearToken() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ORG_KEY);
}

export function setOrgId(orgId: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(ORG_KEY, orgId);
}

export function getOrgId() {
  return typeof window === "undefined" ? null : localStorage.getItem(ORG_KEY);
}

function decodeBase64Url(str: string): string {
  // Convert base64url to standard base64
  let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  // Add padding if needed
  const pad = base64.length % 4;
  if (pad === 2) base64 += "==";
  else if (pad === 3) base64 += "=";
  return atob(base64);
}

export function getTokenExpirySeconds(): number | null {
  const token = getToken();
  if (!token) return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 3 || !parts[1]) return null;
    const payload = JSON.parse(decodeBase64Url(parts[1]));
    if (!payload.exp) return null;
    return payload.exp - Math.floor(Date.now() / 1000);
  } catch {
    return null;
  }
}
