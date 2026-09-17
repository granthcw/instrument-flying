import datetime as dt
import pytest

from kjyo_backtest.geo import bounding_box, haversine_nm, km_to_nm, nm_to_km
from kjyo_backtest.periods import (
    DAY, NIGHT, daypart, daypart_for, dayparts_between, lead_day, lead_hours,
)

KJYO = (39.0780, -77.5575)
KIAD = (38.9445, -77.4558)
TZ = "America/New_York"


def test_haversine_zero_distance():
    assert haversine_nm(*KJYO, *KJYO) == pytest.approx(0.0, abs=1e-9)


def test_haversine_kjyo_to_kiad():
    # Published separation is "about 10 miles"; 9.3 nm == 10.7 statute miles.
    assert haversine_nm(*KJYO, *KIAD) == pytest.approx(9.31, abs=0.05)


def test_haversine_is_symmetric():
    assert haversine_nm(*KJYO, *KIAD) == pytest.approx(haversine_nm(*KIAD, *KJYO))


def test_one_degree_of_latitude_is_sixty_nm():
    assert haversine_nm(39.0, -77.0, 40.0, -77.0) == pytest.approx(60.0, abs=0.1)


def test_bounding_box_contains_every_point_within_the_radius():
    """The box must be a superset of the circle the haversine filter applies.

    GLM filtering does a cheap box test before the expensive distance test, so
    a box that clipped the circle would silently drop real flashes. Swept over
    all bearings rather than just the cardinals, since the box is tightest on
    the diagonals.
    """
    import math

    lat, lon, radius = KJYO[0], KJYO[1], 20.0
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius)
    for bearing_deg in range(0, 360, 5):
        b = math.radians(bearing_deg)
        ang = radius / 3440.065
        p1 = math.radians(lat)
        p2 = math.asin(math.sin(p1) * math.cos(ang) + math.cos(p1) * math.sin(ang) * math.cos(b))
        l2 = math.radians(lon) + math.atan2(
            math.sin(b) * math.sin(ang) * math.cos(p1),
            math.cos(ang) - math.sin(p1) * math.sin(p2))
        plat, plon = math.degrees(p2), math.degrees(l2)
        assert haversine_nm(lat, lon, plat, plon) == pytest.approx(radius, abs=1e-6)
        assert min_lat <= plat <= max_lat, f"bearing {bearing_deg} escaped in latitude"
        assert min_lon <= plon <= max_lon, f"bearing {bearing_deg} escaped in longitude"


def test_bounding_box_widens_with_radius():
    narrow = bounding_box(*KJYO, 5.0)
    wide = bounding_box(*KJYO, 20.0)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])
    assert (wide[3] - wide[2]) > (narrow[3] - narrow[2])


def test_bounding_box_is_wider_in_longitude_at_mid_latitude():
    min_lat, max_lat, min_lon, max_lon = bounding_box(39.078, -77.5575, 10.0)
    assert (max_lon - min_lon) > (max_lat - min_lat)


def test_nm_km_round_trip():
    assert km_to_nm(nm_to_km(10.0)) == pytest.approx(10.0)


def test_dayparts_are_twelve_hours_in_both_dst_regimes():
    for date in (dt.date(2025, 7, 15), dt.date(2025, 1, 15)):
        for kind in (DAY, NIGHT):
            p = daypart(date, kind, TZ)
            assert (p.end_utc - p.start_utc) == dt.timedelta(hours=12)


def test_spring_forward_night_is_eleven_hours():
    p = daypart(dt.date(2025, 3, 8), NIGHT, TZ)
    assert (p.end_utc - p.start_utc) == dt.timedelta(hours=11)


def test_fall_back_night_is_thirteen_hours():
    p = daypart(dt.date(2025, 11, 1), NIGHT, TZ)
    assert (p.end_utc - p.start_utc) == dt.timedelta(hours=13)


def test_daypart_bounds_are_local_seven_and_nineteen():
    p = daypart(dt.date(2025, 7, 15), DAY, TZ)
    assert p.start_utc == dt.datetime(2025, 7, 15, 11, tzinfo=dt.timezone.utc)   # 07:00 EDT
    assert p.end_utc == dt.datetime(2025, 7, 15, 23, tzinfo=dt.timezone.utc)     # 19:00 EDT


def test_night_belongs_to_the_date_it_starts_on():
    # 03:00Z on Jul 15 is 23:00 EDT on Jul 14 -> the night of the 14th.
    p = daypart_for(dt.datetime(2025, 7, 15, 3, tzinfo=dt.timezone.utc), TZ)
    assert p.local_date == dt.date(2025, 7, 14)
    assert p.kind == NIGHT


def test_daypart_for_midday_is_day():
    p = daypart_for(dt.datetime(2025, 7, 15, 17, tzinfo=dt.timezone.utc), TZ)  # 13:00 EDT
    assert p.kind == DAY and p.local_date == dt.date(2025, 7, 15)


def test_daypart_boundaries_are_half_open():
    p = daypart(dt.date(2025, 7, 15), DAY, TZ)
    assert p.contains(p.start_utc)
    assert not p.contains(p.end_utc)


def test_dayparts_between_covers_every_day_twice():
    parts = dayparts_between(dt.date(2025, 7, 1), dt.date(2025, 7, 3), TZ)
    assert len(parts) == 6
    assert [p.kind for p in parts] == [DAY, NIGHT] * 3


def test_daypart_keys_are_unique():
    parts = dayparts_between(dt.date(2025, 5, 1), dt.date(2025, 9, 30), TZ)
    assert len({p.key for p in parts}) == len(parts)


def test_lead_hours_and_lead_day():
    pulled = dt.datetime(2025, 7, 27, 21, 15, tzinfo=dt.timezone.utc)   # 17:15 EDT
    p = daypart(dt.date(2025, 7, 28), DAY, TZ)
    assert lead_hours(pulled, p.start_utc) == pytest.approx(13.75)
    assert lead_day(pulled, dt.date(2025, 7, 28), TZ) == 1
    assert lead_day(pulled, dt.date(2025, 7, 27), TZ) == 0


def test_lead_hours_is_negative_for_a_past_period():
    pulled = dt.datetime(2025, 7, 27, 21, 15, tzinfo=dt.timezone.utc)
    p = daypart(dt.date(2025, 7, 26), DAY, TZ)
    assert lead_hours(pulled, p.start_utc) < 0
