"""Order routing against a fake Alpaca client.

Being able to do this at all is the point of making the clients lazy: nothing here needs
credentials, a network, or a paper account. The stop re-assertion tests are regression
cover for the bug where a position could run overnight with no stop behind it.
"""

import pytest
from alpaca.trading.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest

import execution as execution_mod
from execution import execution_instance

TICKER = "AAPL"
ATR_STOP_DISTANCE = 4.0  # ATR of 2.0 × the default ATR_MULTIPLIER of 2.0


# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeOrder:
    def __init__(self, oid, side, order_type, qty, status, fill_price=None):
        self.id = oid
        self.side = side
        self.type = order_type
        self.qty = str(qty)
        self.status = status
        self.filled_qty = str(qty) if status == OrderStatus.FILLED else "0"
        self.filled_avg_price = str(fill_price) if fill_price is not None else None


class FakePosition:
    def __init__(self, qty, avg_entry_price):
        self.qty = str(qty)
        self.avg_entry_price = str(avg_entry_price)


class FakeClient:
    """Market orders fill instantly at `fill_price`; stop orders rest."""

    def __init__(self, position=None, resting=(), fill_price=100.0, orders_raise=False):
        self.position = position
        self.resting = list(resting)
        self.fill_price = fill_price
        self.orders_raise = orders_raise
        self.submitted = []
        self.cancelled = []
        self._orders = {o.id: o for o in self.resting}
        self._seq = 0

    def get_open_position(self, ticker):
        if self.position is None:
            raise Exception("position does not exist for AAPL")
        return self.position

    def get_orders(self, request):
        if self.orders_raise:
            raise Exception("api unavailable")
        return list(self.resting)

    def cancel_order_by_id(self, order_id):
        self.cancelled.append(order_id)
        self.resting = [o for o in self.resting if o.id != order_id]

    def submit_order(self, request):
        self.submitted.append(request)
        self._seq += 1
        oid = f"order-{self._seq}"

        if isinstance(request, MarketOrderRequest):
            order = FakeOrder(
                oid, request.side, OrderType.MARKET, request.qty,
                OrderStatus.FILLED, fill_price=self.fill_price,
            )
        else:
            order = FakeOrder(
                oid, request.side, OrderType.STOP, request.qty, OrderStatus.NEW
            )
            self.resting.append(order)

        self._orders[oid] = order
        return order

    def get_order_by_id(self, order_id):
        return self._orders[order_id]

    # convenience views for assertions
    @property
    def market_orders(self):
        return [r for r in self.submitted if isinstance(r, MarketOrderRequest)]

    @property
    def stop_orders(self):
        return [r for r in self.submitted if isinstance(r, StopOrderRequest)]


def stop_order(oid, side, qty):
    return FakeOrder(oid, side, OrderType.STOP, qty, OrderStatus.NEW)


@pytest.fixture
def wire(monkeypatch, bars):
    """Install a fake client and return (client, bars_frame, run_decision)."""

    def _wire(*, position=None, resting=(), decision="HOLD", allow_short=True,
              dynamic_sizing=False, fill_price=100.0, closes=None, orders_raise=False):
        client = FakeClient(
            position=position, resting=resting, fill_price=fill_price,
            orders_raise=orders_raise,
        )
        monkeypatch.setattr(execution_mod, "_get_trading_client", lambda: client)
        monkeypatch.setattr(execution_mod, "ALLOW_SHORT", allow_short)
        monkeypatch.setattr(execution_mod, "DYNAMIC_POSITION_SIZING", dynamic_sizing)

        prices = closes if closes is not None else [100.0] * 40
        df = bars(prices, highs=[p + 1.0 for p in prices], lows=[p - 1.0 for p in prices])

        evaluation = {
            "RSI": None, "EMA": None, "MACD": None, "Signal": None,
            "Decision": decision, "ticker_data": df,
        }

        def run():
            return execution_instance._execute_decision(TICKER, df, evaluation)

        return client, df, run

    return _wire


# ── Position transitions ──────────────────────────────────────────────────────


def test_buy_from_flat_opens_a_long_and_protects_it(wire):
    client, _, run = wire(position=None, decision="BUY")
    run()

    assert len(client.market_orders) == 1
    assert client.market_orders[0].side == OrderSide.BUY
    assert len(client.stop_orders) == 1
    assert client.stop_orders[0].side == OrderSide.SELL


def test_buy_while_short_covers_then_reverses_in_one_order(wire):
    """A reversal must buy back the short *and* open the long, or the position ends up
    half-sized without anyone noticing."""
    client, _, run = wire(position=FakePosition(-10, 100.0), decision="BUY")
    run()

    # DYNAMIC_POSITION_SIZING off → 1 new share, plus 10 to cover
    assert int(client.market_orders[0].qty) == 11
    assert client.market_orders[0].side == OrderSide.BUY


def test_sell_while_long_flattens_without_opening_a_short(wire):
    client, _, run = wire(position=FakePosition(10, 100.0), decision="SELL")
    run()

    assert len(client.market_orders) == 1
    assert client.market_orders[0].side == OrderSide.SELL
    assert int(client.market_orders[0].qty) == 10
    assert client.stop_orders == [], "flattening leaves nothing to protect"


def test_sell_from_flat_opens_a_short_when_shorting_is_enabled(wire):
    client, _, run = wire(position=None, decision="SELL", allow_short=True)
    run()

    assert len(client.market_orders) == 1
    assert client.market_orders[0].side == OrderSide.SELL
    assert client.stop_orders[0].side == OrderSide.BUY, "a short is stopped by buying"


def test_sell_from_flat_does_nothing_when_shorting_is_disabled(wire):
    client, _, run = wire(position=None, decision="SELL", allow_short=False)
    run()

    assert client.submitted == []


def test_buy_while_already_long_does_not_add(wire):
    client, _, run = wire(position=FakePosition(10, 100.0), decision="BUY",
                          resting=[stop_order("s1", OrderSide.SELL, 10)])
    run()

    assert client.market_orders == []


def test_unknown_position_aborts_rather_than_guessing(wire, monkeypatch):
    client, _, run = wire(position=FakePosition(10, 100.0), decision="BUY")
    monkeypatch.setattr(execution_instance, "get_current_position", lambda t: None)
    run()

    assert client.submitted == [], "an unreadable position must never be traded against"


# ── Stops are GTC ─────────────────────────────────────────────────────────────


def test_stops_are_gtc_so_they_survive_the_close(wire):
    """Regression: a DAY stop is cancelled by the broker at the close while the position
    persists, leaving the overnight gap completely unhedged."""
    client, _, run = wire(position=None, decision="BUY")
    run()

    assert client.stop_orders[0].time_in_force == TimeInForce.GTC


def test_market_orders_stay_day_orders(wire):
    client, _, run = wire(position=None, decision="BUY")
    run()

    assert client.market_orders[0].time_in_force == TimeInForce.DAY


# ── Stop re-assertion on HOLD ─────────────────────────────────────────────────


def test_hold_with_a_correctly_sized_stop_does_nothing(wire):
    client, _, run = wire(
        position=FakePosition(10, 100.0),
        resting=[stop_order("s1", OrderSide.SELL, 10)],
        decision="HOLD",
    )
    run()

    assert client.submitted == []
    assert client.cancelled == []


def test_hold_on_an_unprotected_long_places_a_stop(wire):
    """The core regression: before this, a HOLD on an open position left it naked
    indefinitely once the original DAY stop had expired."""
    client, _, run = wire(position=FakePosition(10, 100.0), resting=[], decision="HOLD")
    run()

    assert len(client.stop_orders) == 1
    placed = client.stop_orders[0]
    assert placed.side == OrderSide.SELL
    assert int(placed.qty) == 10
    assert placed.stop_price == pytest.approx(100.0 - ATR_STOP_DISTANCE)


def test_hold_on_an_unprotected_short_places_a_stop_above_entry(wire):
    client, _, run = wire(position=FakePosition(-10, 100.0), resting=[], decision="HOLD")
    run()

    placed = client.stop_orders[0]
    assert placed.side == OrderSide.BUY
    assert placed.stop_price == pytest.approx(100.0 + ATR_STOP_DISTANCE)


def test_hold_replaces_a_mis_sized_stop(wire):
    """A partial stop fill leaves a stop covering less than the position holds."""
    client, _, run = wire(
        position=FakePosition(10, 100.0),
        resting=[stop_order("stale", OrderSide.SELL, 4)],
        decision="HOLD",
    )
    run()

    assert "stale" in client.cancelled
    assert int(client.stop_orders[0].qty) == 10


def test_hold_ignores_stops_on_the_wrong_side(wire):
    """A resting BUY stop does not protect a long position."""
    client, _, run = wire(
        position=FakePosition(10, 100.0),
        resting=[stop_order("wrong-side", OrderSide.BUY, 10)],
        decision="HOLD",
    )
    run()

    assert len(client.stop_orders) == 1, "a long still needs its own SELL stop"


def test_hold_flattens_when_price_is_already_through_the_stop_level(wire):
    """Entry at 100 with a 4.00 stop distance puts the stop at 96; price is 90. The
    stop should already have fired, and the broker rejects a stop on the wrong side of
    the market — so exit rather than pretend to be protected."""
    client, _, run = wire(
        position=FakePosition(10, 100.0),
        resting=[],
        decision="HOLD",
        closes=[90.0] * 40,
    )
    run()

    assert len(client.market_orders) == 1
    assert client.market_orders[0].side == OrderSide.SELL
    assert client.stop_orders == []


def test_hold_does_not_stack_a_stop_when_the_order_lookup_fails(wire):
    """An unreadable order book is not the same as an empty one — guessing would risk
    two live stops against one position."""
    client, _, run = wire(
        position=FakePosition(10, 100.0), decision="HOLD", orders_raise=True
    )
    run()

    assert client.submitted == []


def test_hold_while_flat_checks_nothing(wire):
    client, _, run = wire(position=None, decision="HOLD")
    run()

    assert client.submitted == []
