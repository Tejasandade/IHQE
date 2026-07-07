import { useState, useEffect } from 'react';
import client from '../api/client';

const SIGNAL_COLORS = {
  macro_alert: '#B8860B',
  mid_alert: '#E6A817',
  active: '#26A69A',
  execute: '#00E676',
  scalp_path: '#EF5350',
  scalp_cont: '#26A69A',
};

const SIGNAL_ICONS = {
  macro_alert: '◈',
  mid_alert: '◆',
  active: '●',
  execute: '⚡',
  scalp_path: '↘',
  scalp_cont: '↗',
};

export default function SignalBoard() {
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('active');

  useEffect(() => {
    const fetch = () => {
      Promise.all([
        client.get('/signals?status=open').catch(() => ({ data: [] })),
        client.get('/trades?status=open').catch(() => ({ data: [] })),
      ]).then(([sigRes, tradeRes]) => {
        setSignals(sigRes.data || []);
        setTrades(tradeRes.data || []);
      }).finally(() => setLoading(false));
    };
    fetch();
    const interval = setInterval(fetch, 5000);
    return () => clearInterval(interval);
  }, []);

  const activeSignals = signals.filter((s) => s.status === 'open');
  const swingSignals = activeSignals.filter((s) => s.trade_type === 'swing');
  const scalpSignals = activeSignals.filter((s) =>
    s.trade_type === 'scalp_path' || s.trade_type === 'scalp_cont'
  );

  if (loading) {
    return <div className="signal-board loading">Loading signals...</div>;
  }

  return (
    <div className="signal-board">
      <div className="signal-header">
        <h2>Signal Board</h2>
        <div className="signal-tabs">
          <button
            className={`tab ${tab === 'active' ? 'active' : ''}`}
            onClick={() => setTab('active')}
          >
            Active ({activeSignals.length})
          </button>
          <button
            className={`tab ${tab === 'trades' ? 'active' : ''}`}
            onClick={() => setTab('trades')}
          >
            Trades ({trades.length})
          </button>
          <button
            className={`tab ${tab === 'history' ? 'active' : ''}`}
            onClick={() => setTab('history')}
          >
            History
          </button>
        </div>
      </div>

      {tab === 'active' && (
        <div className="signal-list">
          {swingSignals.length > 0 && (
            <div className="signal-section">
              <h3 className="section-label">Swing Signals</h3>
              {swingSignals.map((sig) => (
                <SignalCard key={sig.signal_id} signal={sig} />
              ))}
            </div>
          )}
          {scalpSignals.length > 0 && (
            <div className="signal-section">
              <h3 className="section-label">Scalp Signals</h3>
              {scalpSignals.map((sig) => (
                <SignalCard key={sig.signal_id} signal={sig} />
              ))}
            </div>
          )}
          {activeSignals.length === 0 && (
            <div className="signal-empty">
              <div className="empty-icon">◇</div>
              <p>No active signals</p>
              <p className="empty-sub">Waiting for cascade gates to confirm</p>
            </div>
          )}
        </div>
      )}

      {tab === 'trades' && (
        <div className="signal-list">
          {trades.length > 0 ? trades.map((trade) => (
            <TradeCard key={trade.trade_id} trade={trade} />
          )) : (
            <div className="signal-empty">
              <div className="empty-icon">◇</div>
              <p>No open trades</p>
            </div>
          )}
        </div>
      )}

      {tab === 'history' && <HistoryPanel />}
    </div>
  );
}

function SignalCard({ signal }) {
  const color = SIGNAL_COLORS[signal.signal_type] || '#888';
  const icon = SIGNAL_ICONS[signal.signal_type] || '○';
  const dirLabel = signal.direction === 'long' ? 'LONG' : 'SHORT';
  const dirColor = signal.direction === 'long' ? '#26A69A' : '#EF5350';

  return (
    <div className="signal-card" style={{ borderLeftColor: color }}>
      <div className="signal-card-header">
        <span className="signal-icon" style={{ color }}>{icon}</span>
        <span className="signal-type" style={{ color }}>
          {signal.signal_type?.toUpperCase().replace('_', ' ')}
        </span>
        <span className="signal-dir" style={{ color: dirColor }}>{dirLabel}</span>
        <span className="signal-gates">{signal.gates_confirmed}/3</span>
      </div>
      <div className="signal-card-body">
        <div className="signal-zone">
          <span className="zone-label">Entry Zone</span>
          <span className="zone-range">
            ${signal.target_lower?.toFixed(2)} — ${signal.target_upper?.toFixed(2)}
          </span>
        </div>
        <div className="signal-meta">
          <span className="signal-trade-type">{signal.trade_type}</span>
          {signal.published_at && (
            <span className="signal-time">
              {new Date(signal.published_at).toLocaleDateString()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function TradeCard({ trade }) {
  const dirColor = trade.direction === 'long' ? '#26A69A' : '#EF5350';
  const pnl = trade.pnl_pct;

  return (
    <div className="trade-card">
      <div className="trade-header">
        <span className="trade-type">{trade.trade_type}</span>
        <span className="trade-dir" style={{ color: dirColor }}>
          {trade.direction?.toUpperCase()}
        </span>
        <span className="trade-tf">{trade.timeframe}</span>
      </div>
      <div className="trade-prices">
        <div className="price-item">
          <span className="price-label">Entry</span>
          <span className="price-value">${trade.entry_price?.toFixed(2)}</span>
        </div>
        <div className="price-item">
          <span className="price-label">SL</span>
          <span className="price-value sl">${trade.stop_loss?.toFixed(2)}</span>
        </div>
        <div className="price-item">
          <span className="price-label">TP</span>
          <span className="price-value tp">${trade.take_profit?.toFixed(2)}</span>
        </div>
        {pnl != null && (
          <div className="price-item">
            <span className="price-label">P&L</span>
            <span className={`price-value ${pnl >= 0 ? 'positive' : 'negative'}`}>
              {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function HistoryPanel() {
  const [history, setHistory] = useState([]);

  useEffect(() => {
    client.get('/signals/history?limit=50')
      .then((res) => setHistory(res.data || []))
      .catch(() => {});
  }, []);

  return (
    <div className="signal-list history">
      {history.length > 0 ? history.map((sig) => (
        <SignalCard key={sig.signal_id} signal={sig} />
      )) : (
        <div className="signal-empty">
          <div className="empty-icon">◇</div>
          <p>No historical signals</p>
        </div>
      )}
    </div>
  );
}
