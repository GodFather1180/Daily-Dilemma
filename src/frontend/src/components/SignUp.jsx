// Sign Up component - create new account with username, email and password

import { useState } from "react";
import { signup, login } from "../api";

const JWT_STORAGE_KEY = "daily_dilemma_jwt";

export default function SignUp({ onSignUpSuccess, onBack }) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);       
  const [showConfirm, setShowConfirm] = useState(false);         
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (!username.trim()) {
      setError("Username is required");
      return;
    }

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }

    setLoading(true);

    try {
      const name = username.trim();

      // Create user account
      await signup(name, email, password);

      // Automatically log in after signup
      const expiry = new Date(Date.now() + 60 * 60 * 1000)
        .toISOString()
        .replace("T", " ")
        .slice(0, 19);

      const response = await login(name, password, expiry);

      if (response.jwt) {
        localStorage.setItem(JWT_STORAGE_KEY, response.jwt);
        onSignUpSuccess(response.jwt);
      }
    } catch (err) {
      if (
        err.message?.includes("already exists") ||
        err.message?.includes("Item already exists")
      ) {
        setError(
          "An account with this email or username already exists. Please try logging in instead.",
        );
      } else {
        setError(err.message || "Failed to create account. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-container">
      <div className="login-box">
        <button
          type="button"
          onClick={onBack}
          className="login-back-button"
        >
          ← Back
        </button>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-field">
            <input
              type="text"
              id="username"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              disabled={loading}
              className="login-input"
            />
          </div>

          <div className="login-field">
            <input
              type="email"
              id="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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

          <div className="login-field password-wrapper">
            <input
              type={showConfirm ? "text" : "password"}
              id="confirmPassword"
              placeholder="Confirm Password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              disabled={loading}
              className="login-input"
            />
            <button
              type="button"
              className="password-eye"
              onClick={() => setShowConfirm((v) => !v)}
              disabled={loading}
            >
              {showConfirm ? "Hide" : "Show"}
            </button>
          </div>

          {error && <div className="login-error">{error}</div>}

          <button
            type="submit"
            className="login-button"
            disabled={
              loading ||
              !username ||
              !email ||
              !password ||
              !confirmPassword
            }
          >
            {loading ? "Creating account..." : "Sign Up"}
          </button>
        </form>
      </div>
    </div>
  );
}
