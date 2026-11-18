"""원본 CSV 내보내기 검증. 모든 API 응답은 가짜이며 실제 네트워크를 쓰지 않는다."""
import csv
import json

import httpx
import pytest

from src.hub_export import ExportError, FIELDS, collect, export, validate_row


def row(dataset, index=0):
    common = {"userType": "내국인관광객", "dtYearMonth": "201711", "userCount": index + 1,
              "useCount": 2, "useCost": 3000}
    if dataset == "597":
        return dict(common, sido="제주도", sigungu="서귀포시", cityGubun="도심",
                    marketType="전체", ageGroup="30대", gender="여")
    return dict(common, districtType="상업지", dtWeek="금")


def transport(status=200, repeat=False, total_change=False):
    def respond(request):
        if status != 200:
            return httpx.Response(status)
        dataset = "597" if "5D5a577" in request.url.path else "608"
        page = int(request.url.params["number"])
        records = [row(dataset, n) for n in range(101)]
        batch = records[:100] if page == 1 or repeat else records[100:]
        return httpx.Response(200, json={"totCnt": 102 if total_change and page > 1 else 101,
                                       "hasMore": page == 1, "data": batch})
    return httpx.MockTransport(respond)


def test_export_preserves_fields_totals_gender_and_roundtrip(tmp_path):
    target = tmp_path / "export"
    receipt = export("fake-secret", target, "201701", "201712", transport())
    assert receipt["app_activated"] is False
    for dataset, filename in [("597", "monthly_597.csv"), ("608", "weekday_608.csv")]:
        with (target / filename).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            assert reader.fieldnames == FIELDS[dataset]
        assert len(rows) == 101
        assert receipt["datasets"][dataset]["roundtrip_equal"]
        assert receipt["datasets"][dataset]["requests"] == 2
        assert "fake-secret" not in (target / filename).read_text(encoding="utf-8-sig")
    assert rows[0]["dtWeek"] == "금"
    assert receipt["datasets"]["597"]["categories"]["gender"] == ["여"]
    assert receipt["datasets"]["597"]["categories"]["marketType"] == ["전체"]
    assert json.loads((target / "receipt.json").read_text(encoding="utf-8")) == receipt


@pytest.mark.parametrize("network", [transport(status=403), transport(repeat=True), transport(total_change=True)])
def test_failure_does_not_publish_partial_files(tmp_path, network):
    target = tmp_path / "export"
    with pytest.raises(ExportError) as error:
        export("fake-secret", target, "201701", "201712", network)
    assert "fake-secret" not in str(error.value)
    assert not target.exists() and not list(tmp_path.iterdir())


def test_existing_files_are_never_overwritten(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("original")
    with pytest.raises(ExportError, match="이미 존재"):
        export("fake-secret", target, "201701", "201712", transport())
    assert marker.read_text() == "original"


@pytest.mark.parametrize("change", [{"gender": None}, {"useCost": "NaN"}, {"dtYearMonth": "202611"},
                                   {"useCount": 1.5}, {"gender": "=1+1"}, {"extra": "unexpected"}])
def test_invalid_rows_are_rejected(change):
    record = row("597") | change
    with pytest.raises(ExportError):
        validate_row(record, "597", "201701", "201712")


def test_request_budget_stops_before_second_page():
    with httpx.Client(transport=transport()) as client:
        with pytest.raises(ExportError, match="상한"):
            collect(client, "597", "fake-secret", "201701", "201712", max_pages=1, delay=0)
