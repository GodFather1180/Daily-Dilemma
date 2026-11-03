// Login component - sign in with username/password or continue as guest

import { useState } from "react";
import { login } from "../api";

const JWT_STORAGE_KEY = "daily_dilemma_jwt";

export default function Login({ onLoginSuccess, onContinueAsGuest, onBack }) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);  
  const [rememberMe, setRememberMe] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      // Calculate expiry (1 hour from now)
      const expiry = new Date(Date.now() + 60 * 60 * 1000)
        .toISOString()
        .replace("T", " ")
        .slice(0, 19);

      const response = await login(name, password, expiry);

      if (response.jwt) {
        localStorage.setItem(JWT_STORAGE_KEY, response.jwt);
        onLoginSuccess(response.jwt);
      }
    } catch (err) {
      setError(err.message || "Invalid credentials. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-container">
      <div className="login-box">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="login-back-button"
          >
            ← Back
          </button>
        )}

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-field">
            <input
              type="text"
              id="username"
              placeholder="Username"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              disabled={loading}
              className="login-input"
            />
          </div>

          <div className="login-field password-wrapper">
            <input
              type={showPassword ? "text" : "password"}
              id="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={loading}
              className="login-input"
            />
            <button
              type="button"
              className="password-eye"
              onClick={() => setShowPassword((v) => !v)}
              disabled={loading}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>

          <div className="login-remember">
            <input
              type="checkbox"
              id="remember"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              disabled={loading}
              className="login-checkbox"
            />
            <label htmlFor="remember" className="login-checkbox-label">
              Remember me
            </label>
          </div>

          {error && <div className="login-error">{error}</div>}

          <button
            type="submit"
            className="login-button"
            disabled={loading || !name || !password}
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>

          <div style={{ textAlign: "center", marginTop: "8px" }}>
            <button
              type="button"
              onClick={onContinueAsGuest}
              className="login-guest-link"
              disabled={loading}
            >
              Continue as guest
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
