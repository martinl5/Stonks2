"""Unit tests for the pure logic in daily_job.py.

The module is imported directly (it does no network I/O at import time).
The `nb` fixture exposes the module's namespace as a dict — assigning to a
key (e.g. nb['Ticker'] = FakeTicker) patches the module global, which is how
the network-dependent tests stub out yahooquery and Telegram.
"""
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import daily_job


@pytest.fixture(scope='module')
def nb():
    return vars(daily_job)


# ---- numeric helpers -------------------------------------------------

def test_is_num(nb):
    assert nb['is_num'](3.2)
    assert nb['is_num'](0)
    assert not nb['is_num'](None)
    assert not nb['is_num'](float('nan'))
    assert not nb['is_num']('NA')


def test_first_valid(nb):
    assert nb['first_valid'](None, float('nan'), 5.0) == 5.0
    assert nb['first_valid'](0, 7) == 0  # zero is a valid value, not falsy-skipped
    assert math.isnan(nb['first_valid'](None, float('nan')))


def test_fmt(nb):
    assert nb['fmt'](3.14159) == '3.14'
    assert nb['fmt'](None) == 'N/A'
    assert nb['fmt'](float('nan')) == 'N/A'
    assert nb['fmt'](1.5, '+.2f') == '+1.50'


def test_safe_float(nb):
    assert nb['safe_float']('22.41') == 22.41
    assert nb['safe_float']('1,234') == 1234.0
    assert math.isnan(nb['safe_float']('NA'))
    assert math.isnan(nb['safe_float'](''))
    assert math.isnan(nb['safe_float'](None))
    assert nb['safe_float'](7) == 7.0


def test_normalize_dividend_yield(nb):
    f = nb['normalize_dividend_yield']
    assert f(0.0044) == pytest.approx(0.44)   # fraction -> percent
    assert f(2.5) == 2.5                       # already percent
    assert f(0.8) == 0.8                       # 80% yield implausible: was a percent
    assert math.isnan(f(None))
    assert math.isnan(f(float('nan')))


def test_estimate_intrinsic_value(nb):
    f = nb['estimate_intrinsic_value']
    # Graham: EPS x (8.5 + 2g), g in percent
    assert f(5.0, 0.10) == pytest.approx(5.0 * (8.5 + 20))
    assert f(5.0, 0.50) == pytest.approx(5.0 * (8.5 + 50))    # growth clamped at 25%
    assert f(5.0, -0.30) == pytest.approx(5.0 * 8.5)          # negative growth clamped at 0
    assert math.isnan(f(-1.0, 0.10))                          # negative EPS
    assert math.isnan(f(5.0, None))
    assert math.isnan(f(None, 0.10))


# ---- recommendation logic --------------------------------------------

def test_recommend_margins(nb):
    f = nb['recommend']
    assert f(10, 1.0, 20, 2.0) == 'Buy'          # well below 85% of both averages
    assert f(17, 1.7, 20, 2.0) == 'Hold'         # exactly at the margin is not Buy
    assert f(24, 2.4, 20, 2.0) == 'Sell'         # above 115% of both averages
    assert f(23, 2.3, 20, 2.0) == 'Hold'         # exactly at the sell margin is not Sell
    assert f(10, 3.0, 20, 2.0) == 'Hold'         # mixed signals


def test_recommend_missing_benchmark(nb):
    f = nb['recommend']
    assert f(10, 1.0, float('nan'), 2.0) == 'Hold (benchmark unavailable)'
    assert f(10, 1.0, None, None) == 'Hold (benchmark unavailable)'
    assert f(float('nan'), 1.0, 20, 2.0) == 'Hold (benchmark unavailable)'


# ---- breadth thrust ---------------------------------------------------

def _series(values):
    idx = pd.bdate_range(end=pd.Timestamp.today(), periods=len(values))
    return pd.Series(values, index=idx)


def test_breadth_thrust_detected_within_window(nb):
    vals = [0] * 5 + [-80] + [0] * 4 + [75]
    assert nb['detect_breadth_thrust'](_series(vals)) is np.True_ or nb['detect_breadth_thrust'](_series(vals)) == True  # noqa: E712


def test_breadth_thrust_not_detected(nb):
    f = nb['detect_breadth_thrust']
    assert not f(_series([0, 10, 20, 30, 75]))            # never oversold
    assert not f(_series([-80] + [0] * 15 + [75]))        # oversold outside the window
    assert not f(_series([-80, 0]))                       # not overbought now
    assert not f(_series([75]))                           # too short, no crash
    assert not f(None)


# ---- Damodaran table parsing ------------------------------------------

def _table_html(headers, rows):
    head = '<tr>' + ''.join(f'<td>{h}</td>' for h in headers) + '</tr>'
    body = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<html><body><table>{head}{body}</table></body></html>'


def test_parse_industry_table_by_header(nb):
    # Trailing PE deliberately NOT at the historical index 3
    rows = [[f'Industry {i}', '10', f'{20 + i}.5', 'x'] for i in range(60)]
    html = _table_html(['Industry Name', 'Number of firms', 'Trailing PE', 'Other'], rows)
    result = nb['parse_industry_table'](html, ('trailing pe',), fallback_col=3)
    assert result['Industry 0'] == 20.5
    assert len(result) == 60


def test_parse_industry_table_fallback_index(nb):
    rows = [[f'Industry {i}', '10', 'x', f'{30 + i}.25'] for i in range(60)]
    html = _table_html(['A', 'B', 'C', 'D'], rows)
    result = nb['parse_industry_table'](html, ('no such header',), fallback_col=3)
    assert result['Industry 5'] == 35.25


def test_parse_industry_table_na_values(nb):
    rows = [[f'Industry {i}', '10', 'x', 'NA' if i == 0 else '12.0'] for i in range(60)]
    html = _table_html(['A', 'B', 'C', 'D'], rows)
    result = nb['parse_industry_table'](html, ('zzz',), fallback_col=3)
    assert math.isnan(result['Industry 0'])
    assert result['Industry 1'] == 12.0


def test_parse_industry_table_too_few_rows(nb):
    html = _table_html(['A', 'B', 'C', 'D'], [['X', '1', '2', '3']])
    with pytest.raises(ValueError):
        nb['parse_industry_table'](html, ('zzz',), fallback_col=3)


# ---- telegram batching -------------------------------------------------

def test_send_in_batches_packs_under_limit(nb):
    sent = []
    nb['send_telegram_message'] = lambda message, parse_mode=None: sent.append(message)
    blocks = [f'block-{i}-' + 'x' * 500 for i in range(16)]
    nb['send_in_batches'](blocks, max_len=3500, pause=0)
    assert all(len(m) <= 3500 for m in sent)
    assert 1 < len(sent) < 16
    joined = '\n'.join(sent)
    assert all(f'block-{i}-' in joined for i in range(16))


# ---- crash protection ---------------------------------------------------

class FakeTicker:
    """Stub for yahooquery.Ticker('^VIX3M') inside compute_crash_signal."""
    closes = [21.0, 21.0, 21.0]

    def __init__(self, symbol):
        self.symbol = symbol

    @property
    def summary_detail(self):
        if FakeTicker.closes is None:
            return {self.symbol: {}}
        return {self.symbol: {'regularMarketPrice': FakeTicker.closes[-1]}}

    def history(self, period='5d'):
        if FakeTicker.closes is None:
            return {}  # yahooquery returns a dict on errors
        dates = pd.bdate_range(end=pd.Timestamp.today(), periods=len(FakeTicker.closes))
        return pd.DataFrame({'close': FakeTicker.closes}, index=dates)


def _vix_data(closes, current=None):
    if closes is None:
        return {'current': float('nan'), 'history': None}
    dates = pd.bdate_range(end=pd.Timestamp.today(), periods=len(closes))
    return {
        'current': current if current is not None else closes[-1],
        'history': pd.DataFrame({'date': dates, 'close': closes}),
    }


def test_crash_signal_normal(nb):
    nb['Ticker'] = FakeTicker
    FakeTicker.closes = [21.0, 21.0, 21.0]
    status, signals = nb['compute_crash_signal'](_vix_data([20.0, 20.0, 20.0]))
    assert status == 'NORMAL'
    assert signals['vix3m_vix_ratio'] == pytest.approx(21.0 / 20.0)


def test_crash_signal_stress(nb):
    nb['Ticker'] = FakeTicker
    FakeTicker.closes = [24.0, 24.0, 24.0]
    status, signals = nb['compute_crash_signal'](_vix_data([30.0, 30.0, 30.0]))
    assert status == 'STRESS'
    assert signals['level_stress'] and signals['term_stress']


def test_crash_signal_crash(nb):
    nb['Ticker'] = FakeTicker
    FakeTicker.closes = [38.0, 38.0, 38.0]
    status, _ = nb['compute_crash_signal'](_vix_data([45.0, 45.0, 45.0]))
    assert status == 'CRASH'


def test_crash_signal_vix3m_missing(nb):
    nb['Ticker'] = FakeTicker
    FakeTicker.closes = None
    status, signals = nb['compute_crash_signal'](_vix_data([30.0, 30.0, 30.0]))
    assert status == 'WARNING'
    assert signals['term_stress'] is None
    msg = nb['build_crash_message'](status, signals)
    assert 'N/A' in msg


def test_crash_signal_vix_missing(nb):
    nb['Ticker'] = FakeTicker
    FakeTicker.closes = [21.0, 21.0, 21.0]
    status, signals = nb['compute_crash_signal'](_vix_data(None))
    assert status == 'UNKNOWN'
    # message must build without raising despite NaN metrics
    msg = nb['build_crash_message'](status, signals)
    assert 'DATA UNAVAILABLE' in msg


# ---- VIX analysis --------------------------------------------------------

def test_analyze_vix_handles_missing_data(nb):
    vix_data = {'current': float('nan'), 'prior': float('nan'),
                'day_high': None, 'day_low': None, 'week_high': float('nan'),
                'week_low': float('nan'), 'week_change_pct': float('nan'),
                'history': None}
    message, alert_type = nb['analyze_vix'](vix_data)
    assert 'DATA UNAVAILABLE' in message
    assert alert_type is None
    assert 'N/A' in message


def test_analyze_vix_extreme(nb):
    vix_data = {'current': 32.0, 'prior': 28.0, 'day_high': 33.0, 'day_low': 30.0,
                'week_high': 33.0, 'week_low': 25.0, 'week_change_pct': 10.0,
                'history': None}
    message, alert_type = nb['analyze_vix'](vix_data)
    assert alert_type == 'extreme'
    assert 'HIGH FEAR' in message


# ---- mcclellan fetch never fabricates ------------------------------------

def test_mcclellan_returns_none_on_fetch_error(nb):
    class FailingRequests:
        @staticmethod
        def get(*args, **kwargs):
            raise requests.ConnectionError('site down')

    original = nb['requests']
    nb['requests'] = FailingRequests
    try:
        assert nb['fetch_mcclellan_oscillator'](days=14) is None
    finally:
        nb['requests'] = original


def test_mcclellan_passes_file_like_to_read_excel(nb, monkeypatch):
    """pandas 3.0 rejects raw bytes in read_excel - the XLS download must be
    wrapped in a file-like object (regression test for the 2026-06-12 run)."""
    class FakeResponse:
        content = b'xls-bytes'

        def raise_for_status(self):
            pass

    class FakeRequests:
        @staticmethod
        def get(*args, **kwargs):
            return FakeResponse()

    seen = {}

    def fake_read_excel(obj, **kwargs):
        seen['file_like'] = hasattr(obj, 'read')
        raise ValueError('stop after capturing the argument')

    monkeypatch.setitem(nb, 'requests', FakeRequests)
    monkeypatch.setattr(pd, 'read_excel', fake_read_excel)
    assert nb['fetch_mcclellan_oscillator'](days=14) is None
    assert seen['file_like'] is True
