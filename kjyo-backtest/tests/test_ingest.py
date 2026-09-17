import datetime as dt
import pytest

from kjyo_backtest.ingest.glm import GOES19_START, GlmHourAgg, bucket_for
from kjyo_backtest.ingest.metar import (
    IFR, LIFR, MVFR, VFR, ceiling_from_layers, flight_category, parse_rows,
)
from kjyo_backtest.ingest.mrms import (
    CONVECTIVE_FLAGS, FLAG_SEVERITY, PRECIP_FLAG_LABELS, STRATIFORM_FLAGS,
    flag_class, precip_flag_key, qpe_key,
)
from kjyo_backtest.ingest.spc import CATEGORY_RANK, _point_in_geometry, outlook_url


# ------------------------------------------------------------------ GLM ----

def test_goes_bucket_switches_on_the_transition_date():
    assert bucket_for(GOES19_START - dt.timedelta(days=1)) == "noaa-goes16"
    assert bucket_for(GOES19_START) == "noaa-goes19"
    assert bucket_for(dt.date(2026, 7, 1)) == "noaa-goes19"


def test_glm_hour_is_complete_only_when_everything_was_read():
    hour = dt.datetime(2025, 7, 27, 4, tzinfo=dt.timezone.utc)
    assert GlmHourAgg(hour, granules_expected=180, granules_read=180).complete
    assert not GlmHourAgg(hour, granules_expected=180, granules_read=179).complete
    assert not GlmHourAgg(hour, granules_expected=180, granules_read=180,
                          granules_failed=1).complete


# ---------------------------------------------------------------- METAR ----

METAR_CSV = """station,valid,tmpf,dwpf,drct,sknt,p01i,vsby,skyc1,skyc2,skyc3,skyc4,skyl1,skyl2,skyl3,skyl4,wxcodes,metar
JYO,2025-07-27 04:35,77.0,77.0,60,13,1.13,1.00,OVC,M,M,M,800,M,M,M,+TSRA,KJYO 270435Z AUTO 06013KT 1SM +TSRA OVC008 25/25 A3009 RMK AO2 LTG DSNT ALQDS P0113
JYO,2025-07-27 21:55,80.6,78.8,240,4,0.00,10.00,CLR,M,M,M,M,M,M,M,,KJYO 272155Z AUTO 24004KT 10SM CLR 27/26 A3000 RMK AO2 LTG DSNT SW
JYO,2025-07-27 05:55,77.0,77.0,180,4,0.00,10.00,SCT,SCT,BKN,M,1400,2100,4100,M,VCTS,KJYO 270555Z AUTO 18004KT 10SM VCTS SCT014 SCT021 BKN041 25/25 A3008 RMK AO2 LTG DSNT E AND SE
"""


def test_parse_rows_extracts_ceiling_and_category():
    rows = parse_rows(METAR_CSV, "KJYO")
    assert len(rows) == 3
    storm = rows[0]
    assert storm.ceiling_ft == 800
    assert storm.vis_sm == 1.0
    assert storm.flight_category == IFR       # 800 ft -> IFR, 1 sm -> IFR
    assert storm.p01i_in == pytest.approx(1.13)


def test_parse_rows_distinguishes_ts_vcts_and_ltg_remark():
    storm, clear, vcts = parse_rows(METAR_CSV, "KJYO")
    assert storm.ts_in_body is True and storm.vcts is False
    assert vcts.vcts is True
    # A remark-only lightning report is neither TS nor VCTS in the body.
    assert clear.ts_in_body is False and clear.vcts is False
    assert clear.ltg_remark is True


def test_ts_matcher_does_not_fire_on_tsno():
    csv = ("station,valid,vsby,skyc1,skyl1,metar\n"
           "JYO,2025-07-27 06:55,10.00,CLR,M,KJYO 270655Z AUTO 10SM CLR 24/22 A3007 RMK AO2 TSNO\n")
    assert parse_rows(csv, "KJYO")[0].ts_in_body is False


def test_ceiling_uses_lowest_broken_or_overcast():
    assert ceiling_from_layers([("SCT", 1400), ("SCT", 2100), ("BKN", 4100)]) == 4100
    assert ceiling_from_layers([("BKN", 900), ("OVC", 1500)]) == 900
    assert ceiling_from_layers([("VV", 200), ("OVC", 1500)]) == 200
    assert ceiling_from_layers([("FEW", 500), ("SCT", 900)]) is None


def test_flight_category_needs_at_least_one_input():
    assert flight_category(None, None) is None
    assert flight_category(None, 10) == VFR


def test_flight_category_takes_the_worse_of_the_two():
    assert flight_category(400, 10) == LIFR
    assert flight_category(5000, 0.5) == LIFR
    assert flight_category(2000, 2.0) == IFR    # MVFR ceiling, IFR visibility


# ----------------------------------------------------------------- MRMS ----

def test_precip_flag_classes_are_disjoint():
    assert not (CONVECTIVE_FLAGS & STRATIFORM_FLAGS)


def test_every_labelled_flag_has_a_severity_and_a_class():
    for flag in PRECIP_FLAG_LABELS:
        assert flag in FLAG_SEVERITY
        assert flag_class(flag) is not None


def test_flag_class_groups_hail_and_tropical_convective_with_convective():
    assert flag_class(6) == "convective"
    assert flag_class(7) == "convective"       # hail
    assert flag_class(96) == "convective"      # tropical convective
    assert flag_class(1) == "stratiform"
    assert flag_class(10) == "stratiform"
    assert flag_class(91) == "stratiform"
    assert flag_class(3) == "frozen"
    assert flag_class(0) == "none"
    assert flag_class(None) is None


def test_convective_flags_outrank_stratiform_in_severity():
    assert min(FLAG_SEVERITY[f] for f in CONVECTIVE_FLAGS) > \
           max(FLAG_SEVERITY[f] for f in STRATIFORM_FLAGS)


def test_mrms_keys_match_the_published_layout():
    t = dt.datetime(2025, 7, 27, 4, 30, tzinfo=dt.timezone.utc)
    assert precip_flag_key(t) == \
        "CONUS/PrecipFlag_00.00/20250727/MRMS_PrecipFlag_00.00_20250727-043000.grib2.gz"
    t2 = dt.datetime(2025, 7, 27, 5, 0, tzinfo=dt.timezone.utc)
    assert qpe_key(t2).endswith(
        "MRMS_MultiSensor_QPE_01H_Pass2_00.00_20250727-050000.grib2.gz")


# ------------------------------------------------------------------ SPC ----

SQUARE = {"type": "Polygon", "coordinates": [[[-78, 38], [-77, 38], [-77, 40], [-78, 40], [-78, 38]]]}
WITH_HOLE = {"type": "Polygon", "coordinates": [
    [[-79, 37], [-76, 37], [-76, 41], [-79, 41], [-79, 37]],
    [[-78, 38], [-77, 38], [-77, 40], [-78, 40], [-78, 38]],
]}


def test_point_in_polygon():
    assert _point_in_geometry(39.078, -77.5575, SQUARE) is True
    assert _point_in_geometry(39.078, -70.0, SQUARE) is False


def test_point_in_polygon_respects_holes():
    # Inside the outer ring but inside the hole too -> not covered.
    assert _point_in_geometry(39.078, -77.5575, WITH_HOLE) is False
    # Inside the outer ring, outside the hole -> covered.
    assert _point_in_geometry(37.5, -77.5, WITH_HOLE) is True


def test_multipolygon():
    multi = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}
    assert _point_in_geometry(39.078, -77.5575, multi) is True


def test_unknown_geometry_type_is_not_a_match():
    assert _point_in_geometry(39.0, -77.0, {"type": "Point", "coordinates": [-77, 39]}) is False


def test_spc_categories_are_ordered_by_severity():
    order = ["TSTM", "MRGL", "SLGT", "ENH", "MDT", "HIGH"]
    ranks = [CATEGORY_RANK[c] for c in order]
    assert ranks == sorted(ranks)


def test_spc_outlook_url_shape():
    url = outlook_url(dt.date(2025, 7, 27), 1, "1200")
    assert url.endswith("/2025/day1otlk_20250727_1200_cat.lyr.geojson")
