import { useEffect, useRef, useState } from 'react';
import { createChart } from 'lightweight-charts';
import client from '../api/client';

const COLORS = {
  background: '#141414',
  text: '#FFFFFF',
  textSecondary: '#888888',
  border: '#2A2A2A',
  gold: '#B8860B',
  bullish: '#26A69A',
  bearish: '#EF5350',
};

export default function EquityPanel() {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  
  const [annualData, setAnnualData] = useState([]);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 500,
      layout: {
        background: { color: COLORS.background },
        textColor: COLORS.text,
        fontFamily: "'Inter', sans-serif",
      },
      grid: {
        vertLines: { color: '#1E1E1E' },
        horzLines: { color: '#1E1E1E' },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: COLORS.textSecondary, style: 2, width: 1 },
        horzLine: { color: COLORS.textSecondary, style: 2, width: 1 },
      },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: COLORS.border,
      },
    });

    const series = chart.addLineSeries({
      color: COLORS.gold,
      lineWidth: 2,
      crosshairMarkerVisible: true,
      lastValueVisible: true,
      priceLineVisible: false,
    });
    
    // Add 0R reference line
    const zeroLine = chart.addLineSeries({
        color: COLORS.textSecondary,
        lineWidth: 1,
        lineStyle: 2,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    client.get('/backtest/equity').then(res => {
      if (res.data && res.data.length > 0) {
        series.setData(res.data);
        
        // Zero line across entire time range
        zeroLine.setData([
            { time: res.data[0].time, value: 0 },
            { time: res.data[res.data.length - 1].time, value: 0 }
        ]);

        // Annotate 2017 Drawdown
        const d2017 = res.data.find(d => new Date(d.time * 1000).getFullYear() === 2017);
        if (d2017) {
            series.setMarkers([
                {
                    time: d2017.time,
                    position: 'belowBar',
                    color: COLORS.bearish,
                    shape: 'arrowDown',
                    text: '2017 Drawdown (-3%)'
                }
            ]);
        }
        
        chart.timeScale().fitContent();
      }
    });

    client.get('/backtest/annual').then(res => {
      if (res.data) setAnnualData(res.data);
    });

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  return (
    <div className="equity-panel">
      <div style={{ padding: '20px', borderBottom: `1px solid ${COLORS.border}` }}>
        <h2 style={{ margin: 0, color: COLORS.gold }}>Strategy Performance (2003 - 2026)</h2>
        <p style={{ margin: '5px 0 0 0', color: COLORS.textSecondary }}>
          Cumulative R-Multiples assuming 1% fixed risk per trade.
        </p>
      </div>
      
      <div ref={containerRef} style={{ width: '100%' }} />

      <div className="annual-table-container" style={{ padding: '20px' }}>
        <h3 style={{ marginTop: 0 }}>Annual Breakdown</h3>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${COLORS.border}`, color: COLORS.textSecondary }}>
              <th style={{ padding: '10px' }}>Year</th>
              <th style={{ padding: '10px' }}>Trades</th>
              <th style={{ padding: '10px' }}>Win Rate</th>
              <th style={{ padding: '10px' }}>Return (R)</th>
            </tr>
          </thead>
          <tbody>
            {annualData.map(row => (
              <tr key={row.year} style={{ borderBottom: `1px solid ${COLORS.border}` }}>
                <td style={{ padding: '10px', fontWeight: 'bold' }}>{row.year}</td>
                <td style={{ padding: '10px' }}>{row.trades}</td>
                <td style={{ padding: '10px' }}>{row.win_rate}%</td>
                <td style={{ padding: '10px', color: row.return_pct >= 0 ? COLORS.bullish : COLORS.bearish }}>
                  {row.return_pct > 0 ? '+' : ''}{row.return_pct}R
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
