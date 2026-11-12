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
