import React, { useState, useEffect, useRef } from 'react';
import './SimulationPanel.css';

export default function SimulationPanel({ onStateUpdate, onCandleBufferUpdate, isActive }) {
  const [startTs, setStartTs] = useState('2024-01-01T00:00:00Z');
  const [endTs, setEndTs] = useState('2024-12-31T23:59:59Z');
  const [timeframe, setTimeframe] = useState('1H');
  const [speed, setSpeed] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);
  
  const [currentSimTime, setCurrentSimTime] = useState(null);
  const [eventSchedule, setEventSchedule] = useState([]);
  
  const wsRef = useRef(null);
  const bufferRef = useRef([]);
  const playIntervalRef = useRef(null);
  const simTimeRef = useRef(null);
  const nextEventIdxRef = useRef(0);
  
  // Scrubber state
  const startMs = new Date(startTs).getTime();
  const endMs = new Date(endTs).getTime();
  const currentMs = currentSimTime ? new Date(currentSimTime).getTime() : startMs;
  const progressPct = Math.max(0, Math.min(100, ((currentMs - startMs) / (endMs - startMs)) * 100));

  useEffect(() => {
    if (!isActive) {
      handlePause();
      return;
    }
    // Fetch event schedule when starting or changing range
    const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
    fetch(`${apiBase}/simulation/events?start_ts=${startTs}&end_ts=${endTs}`)
      .then(r => r.json())
      .then(data => {
        setEventSchedule(data.events || []);
      })
      .catch(console.error);
  }, [isActive, startTs, endTs]);

  const connectWebSocket = () => {
    if (wsRef.current) wsRef.current.close();
    
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = import.meta.env.VITE_WS_URL || `${wsProtocol}//${window.location.host}/api`;
    wsRef.current = new WebSocket(`${wsHost}/simulation/stream`);
    wsRef.current.onopen = () => {
      wsRef.current.send(JSON.stringify({ start_ts: startTs, end_ts: endTs, timeframe, speed }));
    };
    
    wsRef.current.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'chunk') {
        const parsed = msg.data.map(d => ({
          ...d,
          time: new Date(d.ts + (d.ts.endsWith('Z') ? '' : 'Z')).getTime() / 1000
        }));
        bufferRef.current = [...bufferRef.current, ...parsed];
        // We will just ask for next if buffer is < 1000 candles
        if (bufferRef.current.length < 1000) {
            wsRef.current.send('next');
        }
      } else if (msg.type === 'done') {
        console.log("Stream finished");
      }
    };
  };

  const checkNextChunk = () => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && bufferRef.current.length < 1000) {
          wsRef.current.send('next');
      }
  };

  const handlePlay = () => {
    if (!wsRef.current) connectWebSocket();
    if (!currentSimTime) {
      setCurrentSimTime(startTs);
      simTimeRef.current = startTs;
      nextEventIdxRef.current = 0;
    }
    setIsPlaying(true);
    
    // Playback loop
    playIntervalRef.current = setInterval(() => {
      // Consume candles from buffer that are <= simTime
      if (bufferRef.current.length > 0) {
        // Advance simTime based on speed
        // e.g. 1H timeframe = 3600000 ms. At 1x speed, maybe advance 1 real minute per 100ms? 
        // Let's assume we advance by 1 candle interval per tick based on speed.
        // Actually, speed = how many candles per second? 
        // At 1x speed, 1 candle per second. At 50x speed, 50 candles per second.
        // So interval is 1000/speed. Let's run interval at e.g. 50ms, and pop N candles.
        
        let candlesToPop = 1;
        if (speed >= 10) candlesToPop = Math.ceil(speed / 20); // 20 ticks per second (50ms interval)
        
        const popped = bufferRef.current.splice(0, candlesToPop);
        checkNextChunk();
        
        if (popped.length > 0) {
          const latestCandle = popped[popped.length - 1];
          const newTime = latestCandle.ts;
          setCurrentSimTime(newTime);
          simTimeRef.current = newTime;
          onCandleBufferUpdate(popped);
          
          // Check event schedule
          while (nextEventIdxRef.current < eventSchedule.length) {
            const nextEventTime = eventSchedule[nextEventIdxRef.current];
            if (new Date(nextEventTime) <= new Date(newTime)) {
              // We crossed an event! Fetch state
              const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
              fetch(`${apiBase}/simulation/state?timestamp=${nextEventTime}`)
                .then(r => r.json())
                .then(state => onStateUpdate(state))
                .catch(console.error);
              nextEventIdxRef.current++;
            } else {
              break;
            }
          }
        }
      }
    }, speed > 5 ? 50 : 1000 / speed);
  };

  const handlePause = () => {
    setIsPlaying(false);
    if (playIntervalRef.current) {
      clearInterval(playIntervalRef.current);
      playIntervalRef.current = null;
    }
  };

  const handleReset = () => {
    handlePause();
    setCurrentSimTime(null);
    simTimeRef.current = null;
    bufferRef.current = [];
    nextEventIdxRef.current = 0;
    if (wsRef.current) wsRef.current.close();
    wsRef.current = null;
    onStateUpdate(null);
    onCandleBufferUpdate([], true); // true = reset flag
  };

  const handleScrub = (e) => {
    const rect = e.target.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const pct = Math.max(0, Math.min(1, x / rect.width));
    const newMs = startMs + (endMs - startMs) * pct;
    const newTime = new Date(newMs).toISOString();
    
    handlePause();
    setCurrentSimTime(newTime);
    simTimeRef.current = newTime;
    
    // Find next event index
    let idx = 0;
    while (idx < eventSchedule.length && new Date(eventSchedule[idx]) <= new Date(newTime)) {
      idx++;
    }
    nextEventIdxRef.current = idx;
    
    // Empty buffer so WS re-syncs
    bufferRef.current = [];
    if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
    }
    
    // Ask server for the state at this exact point
    const apiBase = import.meta.env.VITE_API_BASE_URL || '/api';
    fetch(`${apiBase}/simulation/state?timestamp=${newTime}`)
      .then(r => r.json())
      .then(state => onStateUpdate(state))
      .catch(console.error);
      
    // Ask server for the last 200 candles before this point for context
    fetch(`${apiBase}/ohlcv/history?timeframe=${timeframe}&end=${newTime}&limit=200`)
      .then(r => r.json())
      .then(candles => onCandleBufferUpdate(candles, true))
      .catch(console.error);
      
    // Reconnect WS with new start time
    setStartTs(newTime); // Wait, if we change startTs it modifies the scrubber range! 
    // We should not modify startTs. We should just pass newTime to the WS as the stream start point.
  };
  
  const handleScrubClick = (e) => {
      handleScrub(e);
      // Connect WS with the scrubbed time as start
      if (wsRef.current) wsRef.current.close();
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsHost = import.meta.env.VITE_WS_URL || `${wsProtocol}//${window.location.host}/api`;
      wsRef.current = new WebSocket(`${wsHost}/simulation/stream`);
      wsRef.current.onopen = () => {
          wsRef.current.send(JSON.stringify({ start_ts: simTimeRef.current, end_ts: endTs, timeframe, speed }));
      };
      // rest of WS setup happens in play
  }

  if (!isActive) return null;

  return (
    <div className="simulation-panel">
      <div className="sim-controls">
        <input type="datetime-local" value={startTs.slice(0,16)} onChange={e => setStartTs(e.target.value + ':00Z')} />
        <input type="datetime-local" value={endTs.slice(0,16)} onChange={e => setEndTs(e.target.value + ':00Z')} />
        
        <select value={speed} onChange={e => setSpeed(Number(e.target.value))}>
          <option value={1}>1x</option>
          <option value={5}>5x</option>
          <option value={10}>10x</option>
          <option value={50}>50x</option>
        </select>
        
        <button onClick={isPlaying ? handlePause : handlePlay}>{isPlaying ? 'Pause' : 'Play'}</button>
        <button onClick={handleReset}>Reset</button>
        
        <span>{currentSimTime ? new Date(currentSimTime).toLocaleString() : 'Ready'}</span>
      </div>
      
      <div className="scrubber-track" onClick={handleScrubClick}>
        <div className="scrubber-fill" style={{ width: `${progressPct}%` }}></div>
        <div className="scrubber-handle" style={{ left: `${progressPct}%` }}></div>
      </div>
    </div>
  );
}
