"use client";

import {
  FormEvent,
  useState
} from "react";


type LoginRole = "admin" | "consumer";

type FormState = {
  username: string;
  password: string;
};

type LoginResponse = {
  account?: {
    username: string;
    role: LoginRole;
  };
  csrf_token?: string;
  detail?: string;
};


const EMPTY_FORM: FormState = {
  username: "",
  password: ""
};


function fieldError(
  username: string,
  password: string,
  role: LoginRole
): string | null {
  if (!username.trim()) {
    return `Enter the ${role} username.`;
  }
  if (!password) {
    return "Enter the password.";
  }
  return null;
}


export default function LoginPortal() {
  const [admin, setAdmin] = useState<FormState>(EMPTY_FORM);
  const [consumer, setConsumer] = useState<FormState>(EMPTY_FORM);

  const [busyRole, setBusyRole] = useState<LoginRole | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submitLogin(
    event: FormEvent<HTMLFormElement>,
    role: LoginRole
  ) {
    event.preventDefault();

    if (busyRole !== null) {
      return;
    }

    const credentials =
      role === "admin"
        ? admin
        : consumer;

    const missing = fieldError(
      credentials.username,
      credentials.password,
      role
    );
    if (missing) {
      setError(missing);
      return;
    }

    setError(null);
    setBusyRole(role);

    try {
      const response = await fetch(
        "/v1/auth/login",
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            username: credentials.username.trim(),
            password: credentials.password,
            role
          })
        }
      );

      const body = (
        await response.json()
      ) as LoginResponse;

      if (
        !response.ok ||
        !body.account ||
        body.account.role !== role
      ) {
        setError("Invalid username or password.");
        return;
      }

      if (body.csrf_token) {
        sessionStorage.setItem(
          "defendcoder_csrf",
          body.csrf_token
        );
      }

      window.location.href = "/workspace";
    } catch {
      setError(
        "Unable to reach DEFENDcoder. Check the connection and try again."
      );
    } finally {
      setBusyRole(null);
    }
  }

  const signingIn = busyRole !== null;

  return (
    <main className="login-shell">
      <div
        className="login-artwork"
        aria-hidden="true"
      />

      <section
        className="portal-overlay"
        aria-label="DEFENDcoder secure login"
      >
        <div className="login-heading">
          <span className="brand-defend">DEFEND</span>
          <span className="brand-coder">coder</span>
          <p>Secure workspace login</p>
        </div>

        <form
          className="login-form admin-form"
          aria-label="Admin Login"
          onSubmit={(event) =>
            submitLogin(event, "admin")
          }
        >
          <h2>Admin</h2>

          <label
            className="portal-label"
            htmlFor="admin-username"
          >
            Username
          </label>

          <input
            id="admin-username"
            name="username"
            type="text"
            placeholder="admin"
            autoComplete="username"
            spellCheck={false}
            value={admin.username}
            onChange={(event) =>
              setAdmin((current) => ({
                ...current,
                username: event.target.value
              }))
            }
            className="portal-input username-input"
            aria-label="Admin username"
          />

          <label
            className="portal-label"
            htmlFor="admin-password"
          >
            Password
          </label>

          <input
            id="admin-password"
            name="password"
            type="password"
            placeholder="••••••••"
            autoComplete="current-password"
            value={admin.password}
            onChange={(event) =>
              setAdmin((current) => ({
                ...current,
                password: event.target.value
              }))
            }
            className="portal-input password-input"
            aria-label="Admin password"
          />

          <button
            type="submit"
            className="portal-submit"
            disabled={signingIn}
            aria-label="Login as admin"
          >
            {busyRole === "admin" ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <form
          className="login-form consumer-form"
          aria-label="Consumer Login"
          onSubmit={(event) =>
            submitLogin(event, "consumer")
          }
        >
          <h2>Consumer</h2>

          <label
            className="portal-label"
            htmlFor="consumer-username"
          >
            Username
          </label>

          <input
            id="consumer-username"
            name="username"
            type="text"
            placeholder="consumer"
            autoComplete="username"
            spellCheck={false}
            value={consumer.username}
            onChange={(event) =>
              setConsumer((current) => ({
                ...current,
                username: event.target.value
              }))
            }
            className="portal-input username-input"
            aria-label="Consumer username"
          />

          <label
            className="portal-label"
            htmlFor="consumer-password"
          >
            Password
          </label>

          <input
            id="consumer-password"
            name="password"
            type="password"
            placeholder="••••••••"
            autoComplete="current-password"
            value={consumer.password}
            onChange={(event) =>
              setConsumer((current) => ({
                ...current,
                password: event.target.value
              }))
            }
            className="portal-input password-input"
            aria-label="Consumer password"
          />

          <button
            type="submit"
            className="portal-submit"
            disabled={signingIn}
            aria-label="Login as consumer"
          >
            {busyRole === "consumer" ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {error ? (
          <div
            className="login-error"
            role="alert"
          >
            {error}
          </div>
        ) : null}
      </section>
    </main>
  );
}