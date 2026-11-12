from fastapi.testclient import TestClient

from research_desk.api import Backend, create_app
from research_desk.examiner.improve import Registry
from research_desk.examiner.model import train
from research_desk.examiner.service import ExaminerService

from .test_examiner_model import NG_TEXT, corpus, quiet


def client(tmp_path, with_model=True):
    models = tmp_path / "models"
    if with_model:
        cases, secs = corpus(80, seed=7)
        ex = train("v1", cases, secs, lambda c: [], log=quiet)
        ex.meta.update({"selection": {"overall": {"f1": 0.4, "n": 10}},
                        "holdout": {"overall": {"f1": 0.38, "n": 9},
                                    "topic_recall": {"non_gaap": {"n": 5, "recall": 0.8}}}})
        ex.save(models)
        reg = Registry(models)
        reg.log({"attempt": True, "version": "v1", "decision": "promote", "reason": "ok"})
        reg.set_champion("v1")
    svc = ExaminerService(models, tmp_path / "letters.jsonl")
    return TestClient(create_app(Backend(data=tmp_path, examiner_service=svc))), models


def test_draft_is_examined_and_not_stored(tmp_path):
    c, _ = client(tmp_path)
    before = sorted(p.name for p in tmp_path.rglob("*"))
    r = c.post("/api/examiner/draft", json={"text": NG_TEXT * 5 + " adjusted ebitda"})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "v1" and body["predictions"][0]["topic"] == "non_gaap"
    assert len(body["predictions"]) == 5 and body["predictions"][0]["label"] == "Non-GAAP measures"
    assert "most directly comparable GAAP measure" in " ".join(body["predictions"][0]["missing"]) \
        or body["predictions"][0]["missing"] == []
    assert sorted(p.name for p in tmp_path.rglob("*")) == before   # nothing written


def test_draft_validation_and_missing_model(tmp_path):
    c, _ = client(tmp_path)
    assert c.post("/api/examiner/draft", json={"text": "   "}).status_code == 422
    c2, _ = client(tmp_path / "empty", with_model=False)
    assert c2.post("/api/examiner/draft", json={"text": "hello"}).status_code == 503


def test_status_and_ticker_validation(tmp_path):
    c, _ = client(tmp_path)
    s = c.get("/api/examiner/status").json()
    assert s["champion"] == "v1" and s["holdout"]["f1"] == 0.38
    assert s["topic_recall"][0]["topic"] == "non_gaap" and s["attempts"][0]["version"] == "v1"
    assert c.get("/api/examiner/ticker/bad$ticker").status_code == 400


def test_short_draft_warns_and_sic_is_validated(tmp_path):
    c, _ = client(tmp_path)
    body = c.post("/api/examiner/draft", json={"text": "adjusted ebitda"}).json()
    assert body["note"] and body["words"] == 2
    long = c.post("/api/examiner/draft", json={"text": NG_TEXT * 60}).json()
    assert long["note"] is None
    assert c.post("/api/examiner/draft", json={"text": "x", "sic": "'; drop"}).status_code == 422


def limited_client(tmp_path, per_ip=2, total=300):
    from research_desk.examiner.limits import UsageGuard

    _, models = client(tmp_path)
    svc = ExaminerService(models, tmp_path / "letters.jsonl")
    guard = UsageGuard(per_ip_daily=per_ip, global_daily=total, enabled=True)
    return TestClient(create_app(Backend(data=tmp_path, examiner_service=svc), guard=guard))


def post(c, ip, text=NG_TEXT * 5):
    return c.post("/api/examiner/draft", json={"text": text}, headers={"x-forwarded-for": ip})


def test_two_per_ip_then_refused_and_ips_are_separate(tmp_path):
    c = limited_client(tmp_path)
    r1 = post(c, "1.1.1.1")
    assert r1.status_code == 200 and r1.headers["X-RateLimit-Remaining"] == "1"
    assert post(c, "1.1.1.1").status_code == 200
    third = post(c, "1.1.1.1")
    assert third.status_code == 429 and "own machine" in third.json()["detail"]
    assert post(c, "2.2.2.2").status_code == 200                    # another visitor is fine
    q = c.get("/api/examiner/quota", headers={"x-forwarded-for": "1.1.1.1"}).json()
    assert q["remaining"] == 0 and q["limit"] == 2


def test_failed_requests_do_not_use_quota_and_spoofing_is_ignored(tmp_path):
    c = limited_client(tmp_path)
    for _ in range(3):
        assert post(c, "3.3.3.3", text="  ").status_code == 422       # invalid: not counted
    assert post(c, "3.3.3.3").status_code == 200
    assert post(c, "3.3.3.3").status_code == 200
    # a caller-supplied hop before the real one does not reset the quota
    assert post(c, "9.9.9.9, 3.3.3.3").status_code == 429


def test_global_cap_and_metrics_are_aggregate(tmp_path):
    c = limited_client(tmp_path, per_ip=5, total=2)
    assert post(c, "4.4.4.4").status_code == 200
    assert post(c, "5.5.5.5").status_code == 200
    assert post(c, "6.6.6.6").status_code == 429                    # site-wide cap
    m = c.get("/api/metrics").json()
    assert m["usage"]["examinations"] == 2 and m["usage"]["distinct_visitors"] == 2
    assert m["endpoints"]["/api/examiner/draft"]["status"]["429"] == 1
    assert "4.4.4.4" not in str(m)                                    # no raw IPs exposed


def test_local_run_is_unlimited(tmp_path):
    c, _ = client(tmp_path)                                           # EXAMINER_PUBLIC unset
    for _ in range(4):
        assert post(c, "7.7.7.7").status_code == 200
