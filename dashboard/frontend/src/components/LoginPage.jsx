import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import './LoginPage.css';

export default function LoginPage() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
    } catch (err) {
      setError('Invalid email or password.');
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-box">
        <h1 className="login-brand">IHQE <span>v3</span></h1>
        <p className="login-subtitle">Interbank Harmonic Quantitative Engine</p>
        
        {error && <div className="login-error">{error}</div>}
        
        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label>Email</label>
            <input 
              type="email" 
              value={email}
              onChange={e => setEmail(e.target.value)}
              required 
              placeholder="admin@ihqe.io"
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input 
              type="password" 
              value={password}
              onChange={e => setPassword(e.target.value)}
              required 
              placeholder="••••••••"
            />
          </div>
          
          <button type="submit" disabled={loading} className="login-btn">
            {loading ? 'Authenticating...' : 'Sign In'}
          </button>
        </form>

        <p className="login-note">
          Security Note: IHQE v3 uses memory-only JWTs. A full page refresh will require you to log in again.
        </p>
      </div>
    </div>
  );
}
