import { useState, useEffect } from 'react';
import client from '../api/client';

const STATUS_COLORS = {
  waiting: '#444444',
  bos_confirmed: '#B8860B',
  fvg_confirmed: '#B8860B',
  zone_entered: '#26A69A',
};

const STATUS_LABELS = {
  waiting: 'Waiting',
  bos_confirmed: 'BOS Confirmed',
  fvg_confirmed: 'FVG Confirmed',
  zone_entered: 'Zone Entered',
};

export default function CascadeStatus({ simulationState = null }) {
  const [cascade, setCascade] = useState({ swing: [], scalp_path: [], scalp_cont: [] });
  const [loading, setLoading] = useState(true);
  const [direction, setDirection] = useState('bullish');

  useEffect(() => {
    if (simulationState) {
      if (simulationState.cascade) {
        setCascade(simulationState.cascade);
      } else {
        setCascade({ swing: [], scalp_path: [], scalp_cont: [] });
      }
      setLoading(false);
      return;
    }
    
    const fetchCascade = () => {
      client.get('/cascade/current')
        .then((res) => setCascade(res.data || { swing: [], scalp_path: [], scalp_cont: [] }))
        .catch(() => {})
        .finally(() => setLoading(false));
    };
    fetchCascade();
    const interval = setInterval(fetchCascade, 5000);
    return () => clearInterval(interval);
  }, [simulationState]);

  const swingTFs = ['12M', '3M', '1M'];
  const scalpTFs = ['4H', '1H'];

  // Filter swing gates by selected direction
  const directionSwing = (cascade.swing || []).filter(
    (g) => g.direction === direction
  );

  const getGateForTF = (gates, tf) => {
    return gates.find((g) => g.timeframe === tf) || { gate_status: 'waiting', timeframe: tf };
  };

  const gatesConfirmed = directionSwing.filter(
    (g) => g.gate_status !== 'waiting'
  ).length;

  // Also count the other direction for the toggle badge
  const otherDirection = direction === 'bullish' ? 'bearish' : 'bullish';
  const otherSwing = (cascade.swing || []).filter((g) => g.direction === otherDirection);
  const otherGates = otherSwing.filter((g) => g.gate_status !== 'waiting').length;

  if (loading) {
    return <div className="cascade-status loading">Loading cascade state...</div>;
  }

  return (
    <div className="cascade-status">
      <div className="cascade-header">
        <h2>Cascade Status</h2>
        <div className="gates-count">
          <span className="gates-number">{gatesConfirmed}</span>
          <span className="gates-label">/3 Gates</span>
        </div>
      </div>

      {/* Direction toggle */}
      <div className="direction-toggle">
        <button
          className={`dir-btn ${direction === 'bullish' ? 'active bullish' : ''}`}
          onClick={() => setDirection('bullish')}
        >
          <span className="dir-arrow">▲</span> Bullish
          {direction !== 'bullish' && otherGates > 0 && (
            <span className="dir-badge">{otherGates}</span>
          )}
          {direction === 'bullish' && gatesConfirmed > 0 && (
            <span className="dir-badge">{gatesConfirmed}</span>
          )}
        </button>
        <button
          className={`dir-btn ${direction === 'bearish' ? 'active bearish' : ''}`}
          onClick={() => setDirection('bearish')}
        >
          <span className="dir-arrow">▼</span> Bearish
          {direction !== 'bearish' && otherGates > 0 && (
            <span className="dir-badge">{otherGates}</span>
          )}
          {direction === 'bearish' && gatesConfirmed > 0 && (
            <span className="dir-badge">{gatesConfirmed}</span>
          )}
        </button>
      </div>

      <div className="cascade-section">
        <h3>Swing Cascade</h3>
        <div className="gate-cards">
          {swingTFs.map((tf) => {
            const gate = getGateForTF(directionSwing, tf);
            const status = gate.gate_status || 'waiting';
            const color = STATUS_COLORS[status];
            const isActive = status === 'zone_entered';
            const isPulsing = status === 'bos_confirmed' || status === 'fvg_confirmed';

            return (
              <div
                key={tf}
                className={`gate-card ${isActive ? 'active' : ''} ${isPulsing ? 'pulsing' : ''}`}
                style={{ borderColor: color }}
              >
                <div className="gate-tf">{tf}</div>
                <div className="gate-dot" style={{ backgroundColor: color }} />
                <div className="gate-label">{STATUS_LABELS[status]}</div>
                {gate.confirmed_at && (
                  <div className="gate-time">
                    {new Date(gate.confirmed_at).toLocaleDateString()}
                  </div>
                )}
                {/* Show grid info if available */}
                {gate.grid_id && (
                  <div className="gate-grid-id" title={gate.grid_id}>
                    Grid active
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="cascade-section">
        <h3>Scalp Layer</h3>
        <div className="gate-cards">
          {scalpTFs.map((tf) => {
            const pathGate = getGateForTF(cascade.scalp_path || [], tf);
            const contGate = getGateForTF(cascade.scalp_cont || [], tf);

            return (
              <div key={tf} className="gate-card scalp">
                <div className="gate-tf">{tf}</div>
                <div className="scalp-types">
                  <div className="scalp-type">
                    <span className="scalp-label">Path</span>
                    <span
                      className="scalp-dot"
                      style={{ backgroundColor: STATUS_COLORS[pathGate.gate_status || 'waiting'] }}
                    />
                  </div>
                  <div className="scalp-type">
                    <span className="scalp-label">Cont</span>
                    <span
                      className="scalp-dot"
                      style={{ backgroundColor: STATUS_COLORS[contGate.gate_status || 'waiting'] }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        {gatesConfirmed < 2 && (
          <div className="scalp-inactive">
            Scalp layer inactive — need ≥2 swing gates
          </div>
        )}
      </div>
    </div>
  );
}
