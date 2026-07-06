import { useState, useEffect } from 'react';
import ChartPanel from './components/ChartPanel';
import CascadeStatus from './components/CascadeStatus';
import SignalBoard from './components/SignalBoard';
import EquityPanel from './components/EquityPanel';
import LoginPage from './components/LoginPage';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import useLivePrice from './hooks/useLivePrice';
import client from './api/client';
import './App.css';

const ALL_TIMEFRAMES = [
  { key: '12M', label: '12-Month' },
  { key: '3M', label: '3-Month' },
  { key: '1M', label: '1-Month' },
  { key: 'W', label: '1-Week' },
  { key: '4H', label: '4-Hour' },
  { key: '1H', label: '1-Hour' },
];

function Dashboard() {
  const { price, connected } = useLivePrice();
  const { logout } = useAuth();
  const [activePanel, setActivePanel] = useState('charts');
  const [masterTf, setMasterTf] = useState('1M');
  const [expandedTf, setExpandedTf] = useState(null);
  const [cascadeData, setCascadeData] = useState(null);

  useEffect(() => {
    client.get('/cascade').then(res => setCascadeData(res.data)).catch(() => {});
    const interval = setInterval(() => {
      client.get('/cascade').then(res => setCascadeData(res.data)).catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const masterTimeframeObj = ALL_TIMEFRAMES.find(tf => tf.key === masterTf) || ALL_TIMEFRAMES[2];
  const contextTimeframes = ALL_TIMEFRAMES.filter(tf => tf.key !== masterTf);

  return (
    <div className="app">
      {/* ─── Top Bar ─────────────────────────────────────────── */}
      <header className="topbar">
        <div className="topbar-brand">
          <span className="brand-icon">◈</span>
          <span className="brand-name">IHQE</span>
          <span className="brand-version">v3</span>
        </div>

        <div className="topbar-price">
          <span className="price-label">XAU/USD</span>
          {price ? (
            <span className="price-value">${price.mid?.toFixed(2)}</span>
          ) : (
            <span className="price-value dim">—</span>
          )}
          <span className={`connection-dot ${connected ? 'live' : 'offline'}`} />
          
          <div className="topbar-status">
            <span className="gate-count">Gates: {cascadeData?.gates_confirmed || 0}/3</span>
            {cascadeData?.signal_type && cascadeData.signal_type !== 'NONE' && (
              <span className={`signal-badge ${cascadeData.direction}`}>{cascadeData.signal_type} {cascadeData.direction}</span>
            )}
          </div>
        </div>

        <nav className="topbar-nav">
          <button
            className={`nav-btn ${activePanel === 'charts' ? 'active' : ''}`}
            onClick={() => setActivePanel('charts')}
          >
            Charts
          </button>
          <button
            className={`nav-btn ${activePanel === 'cascade' ? 'active' : ''}`}
            onClick={() => setActivePanel('cascade')}
          >
            Cascade
          </button>
          <button
            className={`nav-btn ${activePanel === 'signals' ? 'active' : ''}`}
            onClick={() => setActivePanel('signals')}
          >
            Signals
          </button>
          <button
            className={`nav-btn ${activePanel === 'performance' ? 'active' : ''}`}
            onClick={() => setActivePanel('performance')}
          >
            Performance
          </button>
        </nav>
      </header>

      {/* ─── Main Content ────────────────────────────────────── */}
      <main className="main-content">
        {activePanel === 'charts' && (
          <div className="charts-panel">
            <div className="dashboard-layout">
              <div className="master-zone">
                <ChartPanel
                  key={masterTimeframeObj.key}
                  timeframe={masterTimeframeObj.key}
                  label={masterTimeframeObj.label}
                />
              </div>
              <div className="context-zone">
                {contextTimeframes.map((tf) => (
                  <div key={tf.key} className="context-chart-wrapper">
                    <ChartPanel
                      timeframe={tf.key}
                      label={tf.label}
                      onPromote={() => setMasterTf(tf.key)}
                      onExpand={() => setExpandedTf(tf.key)}
                    />
                  </div>
                ))}
              </div>
            </div>
            
            {expandedTf && (
              <div className="chart-modal-overlay" onClick={() => setExpandedTf(null)}>
                <div className="chart-modal-content" onClick={e => e.stopPropagation()}>
                  <button className="close-modal-btn" onClick={() => setExpandedTf(null)}>×</button>
                  <ChartPanel
                    timeframe={expandedTf}
                    label={ALL_TIMEFRAMES.find(t => t.key === expandedTf)?.label}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {activePanel === 'cascade' && (
          <div className="cascade-panel">
            <CascadeStatus />
          </div>
        )}

        {activePanel === 'signals' && (
          <div className="signals-panel">
            <SignalBoard />
          </div>
        )}

        {activePanel === 'performance' && (
          <div className="performance-panel">
            <EquityPanel />
          </div>
        )}
      </main>
    </div>
  );
}

function AppContent() {
  const { token, loading } = useAuth();

  if (loading) {
    return <div style={{height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff'}}>Loading...</div>;
  }

  if (!token) {
    return <LoginPage />;
  }

  return <Dashboard />;
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
