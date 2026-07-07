import React, { useState, useEffect } from 'react';
import apiClient from '../api/client';

const AlignmentGrid = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [scoreRes, conflictRes] = await Promise.all([
          apiClient.get('/intelligence/score'),
          apiClient.get('/intelligence/conflicts')
        ]);
        
        setData({
          composite_score: scoreRes.data.composite_score,
          biases: scoreRes.data.biases,
          path_scalp: conflictRes.data.path_scalp
        });
      } catch (err) {
        console.error("Failed to fetch intelligence data", err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 5000); // Poll every 5 seconds
    return () => clearInterval(interval);
  }, []);

  if (loading || !data) return <div className="alignment-grid-loading">Loading Alignment...</div>;

  const timeframes = ['12M', '3M', '1M', '4H', '1H'];
  
  const getBlockColor = (bias) => {
    switch (bias) {
      case 2: return '#1B5E20'; // dark green
      case 1: return '#4CAF50'; // light green
      case -1: return '#F44336'; // light red
      case -2: return '#B71C1C'; // dark red
      default: return '#9E9E9E'; // grey for 0
    }
  };

  return (
    <div className="alignment-grid-container" style={{
      display: 'flex', 
      alignItems: 'center', 
      gap: '20px', 
      padding: '15px', 
      backgroundColor: '#1E1E1E',
      borderRadius: '8px',
      marginBottom: '20px'
    }}>
      <div className="blocks-container" style={{ display: 'flex', gap: '8px' }}>
        {timeframes.map(tf => {
          const bias = data.biases[tf] || 0;
          return (
            <div key={tf} className="tf-block" style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              width: '50px',
              height: '50px',
              backgroundColor: getBlockColor(bias),
              borderRadius: '4px',
              color: 'white',
              fontWeight: 'bold',
              fontSize: '14px',
              boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
            }}>
              {tf}
            </div>
          );
        })}
      </div>

      <div className="score-container" style={{ 
        display: 'flex', 
        alignItems: 'baseline',
        color: '#E0E0E0',
        marginLeft: '10px'
      }}>
        <span style={{ fontSize: '12px', marginRight: '8px', textTransform: 'uppercase' }}>Composite:</span>
        <span style={{ 
          fontSize: '24px', 
          fontWeight: 'bold',
          color: data.composite_score >= 10 ? '#4CAF50' : (data.composite_score <= -10 ? '#F44336' : '#FFFFFF')
        }}>
          {data.composite_score.toFixed(1)}
        </span>
      </div>

      {data.path_scalp && (
        <div className="conflict-badge" style={{
          marginLeft: 'auto',
          backgroundColor: '#FF9800',
          color: '#121212',
          padding: '6px 12px',
          borderRadius: '16px',
          fontWeight: 'bold',
          fontSize: '12px',
          textTransform: 'uppercase',
          boxShadow: '0 0 10px rgba(255,152,0,0.5)'
        }}>
          ⚠️ Path Scalp Conflict
        </div>
      )}
    </div>
  );
};

export default AlignmentGrid;
