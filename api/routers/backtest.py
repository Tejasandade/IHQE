import os
import sys
import pandas as pd
from fastapi import APIRouter
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

router = APIRouter()

def get_backtest_df():
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'backtest_results.csv')
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame()

@router.get("/backtest/trades")
def get_trades():
    df = get_backtest_df()
    if df.empty:
        return []
    return df.to_dict('records')

@router.get("/backtest/equity")
def get_equity():
    df = get_backtest_df()
    if df.empty:
        return []
    
    scalp = df[df['trade_type'] == 'scalp'].copy()
    if scalp.empty:
        return []
        
    scalp['exit_ts'] = pd.to_datetime(scalp['exit_ts'])
    scalp = scalp.sort_values('exit_ts')
    
    scalp['r_pnl'] = scalp.apply(
        lambda row: row['rr_ratio'] if row['pnl_pct'] > 0 else -1.0, 
        axis=1
    )
    
    scalp['equity'] = scalp['r_pnl'].cumsum()
    
    # Format for lightweight charts: {time: UNIX_TIMESTAMP, value: float}
    equity_curve = []
    
    for _, row in scalp.iterrows():
        # UNIX timestamp in seconds
        ts = int(row['exit_ts'].timestamp())
        equity_curve.append({
            "time": ts,
            "value": float(row['equity'])
        })
        
    # Remove consecutive duplicates if any
    filtered = []
    seen = set()
    for pt in equity_curve:
        if pt['time'] not in seen:
            seen.add(pt['time'])
            filtered.append(pt)
            
    return filtered

@router.get("/backtest/annual")
def get_annual():
    df = get_backtest_df()
    if df.empty:
        return []
        
    scalp = df[df['trade_type'] == 'scalp'].copy()
    if scalp.empty:
        return []
        
    scalp['exit_ts'] = pd.to_datetime(scalp['exit_ts'])
    scalp['year'] = scalp['exit_ts'].dt.year
    
    scalp['r_pnl'] = scalp.apply(
        lambda row: row['rr_ratio'] if row['pnl_pct'] > 0 else -1.0, 
        axis=1
    )
    
    annual = scalp.groupby('year').agg(
        trades=('trade_id', 'count'),
        wins=('pnl_pct', lambda x: (x > 0).sum()),
        return_pct=('r_pnl', 'sum')
    ).reset_index()
    
    annual['win_rate'] = (annual['wins'] / annual['trades'] * 100).round(1)
    annual['return_pct'] = annual['return_pct'].round(2)
    
    # Sort descending (newest first)
    annual = annual.sort_values('year', ascending=False)
    
    return annual[['year', 'trades', 'win_rate', 'return_pct']].to_dict('records')
