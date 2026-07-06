"""Live network tests — opt-in via ``pytest -m live``.

These hit the real Nominatim + Overpass endpoints. They are excluded from the
default gate (``pytest -m "not live"``) because they depend on the live OSM
infrastructure and can be rate-limited or temporarily flaky.

Run them on demand to verify the SDK still talks to the real APIs::

    pytest -m live
"""

from __future__ import annotations

import pytest

from letsfs import LetsFS, LetsFSError


pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def ls() -> LetsFS:
    return LetsFS()


def test_live_resolve_location(ls):
    loc = ls.resolve_location("Paris")
    assert 48.0 < loc.lat < 49.0
    assert 2.0 < loc.lon < 3.0
    assert "Paris" in loc.display_name
    assert len(loc.boundingbox) == 4
    # Overpass bbox order is south,west,north,east.
    s, w, n, e = [float(x) for x in loc.boundingbox]
    assert s < n
    assert w < e


def test_live_search_small_city(ls):
    """Pick a small city so Overpass returns quickly with a manageable result set."""
    res = ls.search("Bali", limit=5)
    assert res.total >= 0  # network/data-dependent
    assert res.returned == min(res.total, 5)
    if res.hotels:
        h = res.hotels[0]
        assert h.name  # unnamed hotels are filtered out
        assert h.osm_id
        assert h.osm_type in {"node", "way", "relation"}


def test_live_search_empty_location_raises(ls):
    with pytest.raises(LetsFSError):
        ls.search("")


def test_live_get_hotel_details_for_known_node(ls):
    """Round-trip: search → take first hotel → fetch its details."""
    res = ls.search("Bali", limit=1)
    if not res.hotels:
        pytest.skip("No hotels returned by Overpass for Bali right now.")
    h = res.hotels[0]
    details = ls.get_hotel_details(h.osm_id, h.osm_type)
    assert details.osm_id == h.osm_id
    assert details.osm_type == h.osm_type
    assert details.tags  # should have at least the tourism=hotel tag


def test_live_get_hotel_details_bad_id_raises(ls):
    with pytest.raises(LetsFSError, match="osm_id"):
        ls.get_hotel_details("not-a-number", "node")
