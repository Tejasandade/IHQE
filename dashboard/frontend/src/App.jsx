import { useState, useEffect } from 'react';
import ChartPanel from './components/ChartPanel';
import CascadeStatus from './components/CascadeStatus';
import SignalBoard from './components/SignalBoard';
import EquityPanel from './components/EquityPanel';
import LoginPage from './components/LoginPage';
import AlignmentGrid from './components/AlignmentGrid';
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
  const [tzMode, setTzMode] = useState('utc');

  useEffect(() => {
    client.get('/cascade/current').then(res => setCascadeData(res.data)).catch(() => {});
    const interval = setInterval(() => {
      client.get('/cascade/current').then(res => setCascadeData(res.data)).catch(() => {});
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
            <span className="gate-count">
              Gates: {cascadeData?.swing ? Math.max(
                cascadeData.swing.filter(g => g.direction === 'bullish' && g.gate_status !== 'waiting').length,
                cascadeData.swing.filter(g => g.direction === 'bearish' && g.gate_status !== 'waiting').length
              ) : 0}/3
            </span>
            {cascadeData?.signal_type && cascadeData.signal_type !== 'NONE' && (
              <span className={`signal-badge ${cascadeData.direction}`}>{cascadeData.signal_type} {cascadeData.direction}</span>
            )}
          </div>
          <div className="topbar-tz">
            <select value={tzMode} onChange={(e) => setTzMode(e.target.value)} className="tz-select">
              <option value="utc">UTC</option>
              <option value="local_12h">Local (12h)</option>
              <option value="local_24h">Local (24h)</option>
            </select>
          </div>
        </div>

        <nav className="topbar-nav">
          {['charts', 'cascade', 'signals', 'performance'].map(tab => (
            <button
              key={tab}
              className={`nav-btn ${activePanel === tab ? 'active' : ''}`}
              onClick={() => setActivePanel(tab)}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
          <button className="nav-btn logout-btn" onClick={logout}>Logout</button>
        </nav>
      </header>

      {/* ─── Main Content ──────────────────────────────────────── */}
      <main className="main-content">
        
        {activePanel === 'charts' && (
          <div className="charts-panel">
            <div className="dashboard-layout">
              <div className="master-zone">
                <ChartPanel
                  key={masterTimeframeObj.key}
                  timeframe={masterTimeframeObj.key}
                  label={masterTimeframeObj.label}
                  livePrice={price}
                  timezoneMode={tzMode}
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
                      livePrice={price}
                      timezoneMode={tzMode}
                    />
                  </div>
                ))}
              </div>
            </div>
            
            {expandedTf && (
              <div className="chart-modal-overlay" onClick={() => setExpandedTf(null)}>
                <div className="chart-modal-content" onClick={e => e.stopPropagation()}>
                  <button className="close-modal-btn" onClick={() => setExpandedTf(null)}>A-</button>
                  <ChartPanel
                    timeframe={expandedTf}
                    label={ALL_TIMEFRAMES.find(t => t.key === expandedTf)?.label}
                    livePrice={price}
                    timezoneMode={tzMode}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {activePanel === 'cascade' && (
          <div className="cascade-panel">
            <AlignmentGrid />
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
