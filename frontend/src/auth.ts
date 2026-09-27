import { Amplify } from "aws-amplify";
import {
  fetchAuthSession,
  signIn,
  signOut,
  confirmSignIn,
  getCurrentUser,
} from "aws-amplify/auth";

const poolId = import.meta.env.VITE_COGNITO_USER_POOL_ID;
const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID;

export function coCognito(): boolean {
  return Boolean(poolId && clientId);
}

if (coCognito()) {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: poolId!,
        userPoolClientId: clientId!,
      },
    },
  });
}

export async function layToken(): Promise<string | null> {
  if (!coCognito()) return null;
  try {
    const session = await fetchAuthSession();
    const token = session.tokens?.idToken?.toString();
    return token ?? null;
  } catch {
    return null;
  }
}

export async function kiemTraDaDangNhap(): Promise<boolean> {
  if (!coCognito()) return true;
  try {
    await getCurrentUser();
    const session = await fetchAuthSession();
    return Boolean(session.tokens?.idToken);
  } catch {
    return false;
  }
}

export async function dangNhap(
  username: string,
  password: string,
): Promise<{ nextStep: string }> {
  const out = await signIn({ username, password });
  return { nextStep: out.nextStep.signInStep };
}

export async function datMatKhauMoi(newPassword: string): Promise<{ nextStep: string }> {
  const out = await confirmSignIn({ challengeResponse: newPassword });
  return { nextStep: out.nextStep.signInStep };
}

export async function dangXuat(): Promise<void> {
  await signOut();
}
