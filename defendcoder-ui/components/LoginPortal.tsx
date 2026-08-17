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

    setError(null);
    setBusyRole(role);

    const credentials =
      role === "admin"
        ? admin
        : consumer;

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
            username: credentials.username,
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
        "Unable to reach DEFENDcoder. Please try again."
      );
    } finally {
      setBusyRole(null);
    }
  }

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
        <form
          className="login-form admin-form"
          aria-label="Admin Login"
          onSubmit={(event) =>
            submitLogin(event, "admin")
          }
        >
          <label
            className="sr-only"
            htmlFor="admin-username"
          >
            Admin username
          </label>

          <input
            id="admin-username"
            name="username"
            type="text"
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
            className="sr-only"
            htmlFor="admin-password"
          >
            Admin password
          </label>

          <input
            id="admin-password"
            name="password"
            type="password"
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
            disabled={busyRole !== null}
            aria-label="Login as admin"
          >
            <span className="sr-only">
              {busyRole === "admin"
                ? "Signing in as admin"
                : "Login as admin"}
            </span>
          </button>
        </form>

        <form
          className="login-form consumer-form"
          aria-label="Consumer Login"
          onSubmit={(event) =>
            submitLogin(event, "consumer")
          }
        >
          <label
            className="sr-only"
            htmlFor="consumer-username"
          >
            Consumer username
          </label>

          <input
            id="consumer-username"
            name="username"
            type="text"
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
            className="sr-only"
            htmlFor="consumer-password"
          >
            Consumer password
          </label>

          <input
            id="consumer-password"
            name="password"
            type="password"
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
            disabled={busyRole !== null}
            aria-label="Login as consumer"
          >
            <span className="sr-only">
              {busyRole === "consumer"
                ? "Signing in as consumer"
                : "Login as consumer"}
            </span>
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
