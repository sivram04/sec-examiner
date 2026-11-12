import argparse
import json
import time
from datetime import date
from pathlib import Path

import httpx

from .config import settings
from .edgar.chunker import chunk_filing
from .edgar.client import EdgarClient
from .edgar.parser import parse_sections

DATA = Path("data")
CHUNKS = DATA / "chunks"
LETTERS = DATA / "examiner" / "letters.jsonl"
FILINGS = DATA / "examiner" / "filings"
MODELS = DATA / "examiner" / "models"
EMBEDS = DATA / "examiner" / "embeddings"


def _tickers(arg: str) -> list[str]:
    from .ingest.universe import SP100

    return SP100 if arg == "sp100" else [t.strip().upper() for t in arg.split(",")]


def _index(fake: bool = False, rerank: bool = True):
    from qdrant_client import QdrantClient

    from .retrieval.index import HybridIndex
    from .retrieval.models import CrossEncoderReranker, FastEmbedder, HashEmbedder

    if fake:
        return HybridIndex(HashEmbedder())
    q = (QdrantClient(url=settings.qdrant_url) if settings.qdrant_url.startswith("http")
         and settings.use_qdrant_server else QdrantClient(path=str(DATA / "qdrant")))
    return HybridIndex(FastEmbedder(), CrossEncoderReranker() if rerank else None, q)


def _load_index(**kw):
    from .ingest.pipeline import load_corpus

    idx = _index(**kw)
    corpus = load_corpus(CHUNKS)
    t = time.time()
    for i in range(0, len(corpus), 512):
        idx.add(corpus[i:i + 512])
    print(f"index ready: {len(corpus):,} chunks ({time.time() - t:.0f}s)")
    return idx


def _risk_factors(ec: EdgarClient, ticker: str, as_of: date | None, n: int | None,
                  since: date | None = None) -> list[tuple[str, str, list]]:
    """(filing_date, accession, risk factors) for 10-Ks, oldest first."""
    from .graph.risks import RiskFactor, split_risk_factors

    filings = ec.filings(ticker, {"10-K"}, as_of, since=since)[:n]
    cache = DATA / "risks"
    cache.mkdir(parents=True, exist_ok=True)
    out = []
    for f in reversed(filings):
        path = cache / f"{f.accession}.json"
        if path.exists():
            rfs = [RiskFactor(**r) for r in json.loads(path.read_text(encoding="utf-8"))]
        else:
            secs = {s.item: s for s in parse_sections(ec.document(f), f.form)}
            sec = secs.get("1A")
            rfs = split_risk_factors(sec.text, sec.headings) if sec else []
            path.write_text(json.dumps([r.__dict__ for r in rfs]), encoding="utf-8")
            time.sleep(0.12)
        if rfs:
            out.append((f.filing_date.isoformat(), f.accession, rfs))
    return out


def main() -> None:
    p = argparse.ArgumentParser(prog="desk")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("filings", help="list SEC filings for a ticker")
    f.add_argument("ticker")
    f.add_argument("--forms", default="10-K,10-Q,8-K")
    f.add_argument("--as-of", type=date.fromisoformat)
    f.add_argument("-n", type=int, default=10)

    s = sub.add_parser("sections", help="parse the latest 10-K/10-Q into sections and chunks")
    s.add_argument("ticker")
    s.add_argument("--form", default="10-K")
    s.add_argument("--as-of", type=date.fromisoformat)
    s.add_argument("--out", help="write chunks as JSONL to this path")

    for name, hlp in (("ingest", "backfill filings and parse them into the corpus"),
                      ("backfill", "queue historical filings onto raw-docs (kafka bus)"),
                      ("parse", "consume raw-docs, parse and chunk into the corpus")):
        c = sub.add_parser(name, help=hlp)
        c.add_argument("--tickers", default="sp100", help="comma list or 'sp100'")
        c.add_argument("--forms", default="10-K,10-Q")
        c.add_argument("--since", type=date.fromisoformat, default=date(2021, 1, 1))
        c.add_argument("--bus", choices=["memory", "kafka"],
                       default="memory" if name == "ingest" else "kafka")
        c.add_argument("--limit", type=int, help="stop after this many filings")

    w = sub.add_parser("watch", help="poll EDGAR for new covered filings and ingest them")
    w.add_argument("--tickers", default="sp100")
    w.add_argument("--forms", default="10-K,10-Q,8-K")
    w.add_argument("--bus", choices=["memory", "kafka"], default="memory")
    w.add_argument("--every", type=int, default=300, help="seconds between polls")
    w.add_argument("--once", action="store_true")

    fx = sub.add_parser("facts", help="load XBRL company facts into the fact store")
    fx.add_argument("--tickers", default="sp100")

    sub.add_parser("stats", help="corpus document and chunk counts")

    r = sub.add_parser("risks", help="diff risk factors between the two latest 10-Ks")
    r.add_argument("ticker")
    r.add_argument("--as-of", type=date.fromisoformat)
    r.add_argument("--show-unchanged", action="store_true")

    rg = sub.add_parser("risk-graph", help="load risk-factor validity spans into the graph")
    rg.add_argument("--tickers", default="sp100")
    rg.add_argument("--since", type=date.fromisoformat, default=date(2021, 1, 1))

    ge = sub.add_parser("graph-extract", help="LLM-extract grounded entities from 10-K Item 1")
    ge.add_argument("--tickers", default="AAPL,MSFT,NVDA")
    ge.add_argument("--since", type=date.fromisoformat, default=date(2022, 1, 1))

    gq = sub.add_parser("graph-query", help="entities named/dropped between two dates")
    gq.add_argument("ticker")
    gq.add_argument("relation", help="HAS_SEGMENT, HAS_EXECUTIVE, SELLS_PRODUCT, "
                                     "NAMES_SUPPLIER, NAMES_CUSTOMER, NAMES_COMPETITOR")
    gq.add_argument("start")
    gq.add_argument("end")

    wc = sub.add_parser("what-changed", help="risks that appeared/disappeared between dates")
    wc.add_argument("ticker")
    wc.add_argument("start")
    wc.add_argument("end")

    q = sub.add_parser("search", help="hybrid search over the corpus")
    q.add_argument("query")
    q.add_argument("--ticker", action="append", default=[])
    q.add_argument("--section", action="append", default=[])
    q.add_argument("--as-of", type=date.fromisoformat)
    q.add_argument("--method", default="hybrid_rerank",
                   choices=["bm25", "dense", "hybrid", "hybrid_rerank"])
    q.add_argument("-k", type=int, default=5)

    bt = sub.add_parser("backtest", help="risk-deterioration signal vs forward excess returns")
    bt.add_argument("--tickers", default="sp100")
    bt.add_argument("--since", type=date.fromisoformat, default=date(2018, 1, 1))
    bt.add_argument("--days", default="63,252", help="forward windows in trading days")
    bt.add_argument("--out", default="evals/results/backtest.json")

    rs = sub.add_parser("research", help="run the agent desk and write a cited note")
    rs.add_argument("ticker")
    rs.add_argument("question")
    rs.add_argument("--as-of", default=date.today().isoformat())
    rs.add_argument("--user", default="default")
    rs.add_argument("--auto", action="store_true", help="skip human-in-the-loop checkpoints")
    rs.add_argument("--out", help="write the Markdown note here")

    xb = sub.add_parser("examiner-build", help="build the SEC comment-letter corpus")
    xb.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 1))
    xb.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    xb.add_argument("--limit", type=int, help="stop after this many kept letters")

    sub.add_parser("examiner-fetch", help="fetch and cache the filings the SEC reviewed")
    sub.add_parser("examiner-embed", help="embed filings' topic passages with local Ollama")

    xi = sub.add_parser("examiner-improve", help="run the self-improvement loop")
    xi.add_argument("--iterations", type=int, default=3)
    xi.add_argument("--max-minutes", type=float, default=120)
    xi.add_argument("--no-llm", action="store_true", help="rule-based proposals only")
    xi.add_argument("--seed", type=Path, help="meta.json whose recipe bootstraps a new registry")
    xi.add_argument("--code", action="store_true",
                    help="let the LLM write a feature plugin (validated, sandboxed, judged)")

    sub.add_parser("examiner-status", help="champion, lineage and recent attempts")
    sub.add_parser("examiner-rollback", help="revert to the previous champion")

    js = sub.add_parser("judge-seal", help="hash-seal the judge after a deliberate change")
    js.add_argument("--yes", action="store_true", help="confirm: you changed the judge on purpose")

    jb = sub.add_parser("judge-baselines", help="score the baselines a system must beat")
    jb.add_argument("--test-from", default="2024-01-01")
    jb.add_argument("-k", type=int, default=5)
    jb.add_argument("--out", default="evals/results/judge_baselines.json")

    e = sub.add_parser("eval-retrieval", help="compare retrieval methods on the golden set")
    e.add_argument("--golden", default="evals/retrieval_golden.jsonl")
    e.add_argument("-k", type=int, default=10)
    e.add_argument("--out", default="evals/results/retrieval.md")

    a = p.parse_args()

    if a.cmd == "filings":
        for fl in EdgarClient().filings(a.ticker, set(a.forms.split(",")), a.as_of)[: a.n]:
            print(f"{fl.filing_date}  {fl.form:6} {fl.accession}  {fl.url}")

    elif a.cmd == "sections":
        ec = EdgarClient()
        fl = ec.filings(a.ticker, {a.form}, a.as_of)[0]
        secs = parse_sections(ec.document(fl), fl.form)
        chunks = chunk_filing(fl, a.ticker, secs)
        print(f"{fl.form} filed {fl.filing_date}  {fl.url}")
        for sec in secs:
            n = sum(c.section == sec.item for c in chunks)
            print(f"  Item {sec.item:6} {sec.title:42} {len(sec.text):>8,} chars "
                  f"{len(sec.tables):>3} tables {n:>4} chunks")
        print(f"total chunks: {len(chunks)}")
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.writelines(json.dumps(c.to_dict()) + "\n" for c in chunks)

    elif a.cmd in ("ingest", "backfill", "parse"):
        from .ingest.bus import make_bus
        from .ingest.pipeline import backfill, parse_stage

        ec, bus = EdgarClient(), make_bus(a.bus, settings.kafka_bootstrap)
        if a.cmd in ("ingest", "backfill"):
            n = backfill(ec, bus, _tickers(a.tickers), set(a.forms.split(",")), a.since)
            print(f"queued {n} filings")
        if a.cmd in ("ingest", "parse"):
            print(f"parsed {parse_stage(ec, bus, CHUNKS, limit=a.limit)} filings")

    elif a.cmd == "watch":
        from .ingest.bus import make_bus
        from .ingest.pipeline import parse_stage
        from .ingest.watcher import Watcher

        ec, bus = EdgarClient(), make_bus(a.bus, settings.kafka_bootstrap)
        wt = Watcher(ec, bus, _tickers(a.tickers), set(a.forms.split(",")),
                     DATA / "watcher_seen.json")
        while True:
            new = wt.poll_once()
            print(f"{time.strftime('%H:%M:%S')} {len(new)} new filings")
            if new and a.bus == "memory":
                parse_stage(ec, bus, CHUNKS)
            if a.once:
                break
            time.sleep(a.every)

    elif a.cmd == "facts":
        from .ingest.facts import FactStore, flatten

        ec, store = EdgarClient(), FactStore(DATA / "facts.db")
        for t in _tickers(a.tickers):
            try:
                n = store.upsert(flatten(t, ec.company_facts(t)))
                print(f"{t:6} {n:>7,} facts")
            except httpx.HTTPError as ex:
                print(f"{t:6} failed: {ex}")
            time.sleep(0.12)

    elif a.cmd == "stats":
        from collections import Counter

        from .ingest.pipeline import load_corpus

        corpus = load_corpus(CHUNKS)
        docs = {c["accession"]: c for c in corpus}
        print(f"documents: {len(docs):,}  chunks: {len(corpus):,}  "
              f"tickers: {len({c['ticker'] for c in corpus})}")
        for form, n in sorted(Counter(c["form"] for c in docs.values()).items()):
            print(f"  {form:6} {n:>6,} documents")

    elif a.cmd == "risks":
        from .graph.risks import diff_risks

        ec = EdgarClient()
        old, new = _risk_factors(ec, a.ticker, a.as_of, 2)[-2:]
        print(f"{a.ticker} 10-K risk factors: {old[0]} ({len(old[2])}) -> {new[0]} "
              f"({len(new[2])})")
        for c in diff_risks(old[2], new[2]):
            if c.kind == "unchanged" and not a.show_unchanged:
                continue
            rf = c.new or c.old
            print(f"  {c.kind.upper():9} {c.similarity:.2f}  {rf.headline[:150]}")

    elif a.cmd == "risk-graph":
        from .graph.risks import stable_snapshots
        from .graph.temporal import TemporalGraph, edges_from_snapshots

        ec, g = EdgarClient(), TemporalGraph(DATA / "graph.db")
        for t in _tickers(a.tickers):
            snaps = stable_snapshots(_risk_factors(ec, t, None, None, a.since))
            edges = edges_from_snapshots(t, "HAS_RISK", "Risk", snaps)
            g.upsert(edges)
            print(f"{t:6} {len(snaps)} 10-Ks -> {len(edges)} risk edges")

    elif a.cmd == "graph-extract":
        from .graph.extract import RELATIONS, Entity, extract
        from .graph.temporal import TemporalGraph, edges_from_snapshots
        from .llm import chat

        if not settings.llm_api_key:
            raise SystemExit("LLM_API_KEY is not set (.env)")
        ec, g = EdgarClient(), TemporalGraph(DATA / "graph.db")
        cache = DATA / "entities"
        cache.mkdir(parents=True, exist_ok=True)

        def llm(system: str, user: str) -> str:
            return chat([{"role": "system", "content": system}, {"role": "user", "content": user}])

        for t in _tickers(a.tickers):
            snaps: dict[str, list] = {rel: [] for rel in RELATIONS.values()}
            for f in reversed(ec.filings(t, {"10-K"}, since=a.since)):
                path = cache / f"{f.accession}.json"
                if path.exists():
                    ents = [Entity(**e) for e in json.loads(path.read_text(encoding="utf-8"))]
                else:
                    secs = {s.item: s for s in parse_sections(ec.document(f), f.form)}
                    ents = extract(secs["1"].text, llm) if "1" in secs else []
                    path.write_text(json.dumps([e.__dict__ for e in ents]), encoding="utf-8")
                for typ, rel in RELATIONS.items():
                    snaps[rel].append((f.filing_date.isoformat(), f.accession,
                                       {e.name: e.quote for e in ents if e.type == typ}))
                print(f"{t:6} {f.filing_date} {len(ents):3} grounded entities")
            for typ, rel in RELATIONS.items():
                g.upsert(edges_from_snapshots(t, rel, typ, snaps[rel]))

    elif a.cmd == "graph-query":
        from .graph.temporal import TemporalGraph

        added, removed = TemporalGraph(DATA / "graph.db").changed_between(
            a.ticker.upper(), a.relation, a.start, a.end)
        for label, es in (("NEW", added), ("DROPPED", removed)):
            for e in es:
                print(f"  {label:8} {e.object}  [{e.source_accession if label == 'NEW' else e.ended_by}]")
                print(f"           \"{e.evidence[:140]}\"")
        print(f"{len(added)} new, {len(removed)} dropped ({a.relation})")

    elif a.cmd == "what-changed":
        from .graph.temporal import TemporalGraph

        added, removed = TemporalGraph(DATA / "graph.db").changed_between(
            a.ticker.upper(), "HAS_RISK", a.start, a.end)
        for label, es in (("NEW", added), ("DROPPED", removed)):
            for e in es:
                src = e.source_accession if label == "NEW" else e.ended_by
                print(f"  {label:8} {e.object[:150]}  [{src}]")
        print(f"{len(added)} new, {len(removed)} dropped risk factors")

    elif a.cmd == "search":
        from .retrieval.index import Filters

        idx = _load_index(rerank=a.method == "hybrid_rerank")
        f = Filters(a.as_of, tuple(t.upper() for t in a.ticker), tuple(a.section))
        for h in idx.search(a.query, f, k=a.k, method=a.method):
            c = h.chunk
            print(f"\n[{h.score:.3f}] {c['ticker']} {c['form']} {c['filing_date']} "
                  f"Item {c['section']} {h.ranks}\n  {c['text'][:300]}...\n  {c['source_url']}")

    elif a.cmd == "backtest":
        from dataclasses import asdict

        from .backtest.study import (
            attach_returns,
            fetch_prices,
            load_prices,
            observations,
            summarize,
        )

        ec, obs = EdgarClient(), []
        for t in _tickers(a.tickers):
            try:
                obs += observations(t, _risk_factors(ec, t, None, None, a.since))
            except (KeyError, httpx.HTTPError) as ex:
                print(f"{t:6} skipped: {ex!r}")
                continue
            print(f"{t:6} {sum(o.ticker == t for o in obs)} filing pairs")
        px_path = DATA / "prices.csv"
        tickers = sorted({o.ticker for o in obs})
        prices = (load_prices(px_path) if px_path.exists()
                  and set(tickers) <= set(load_prices(px_path))
                  else fetch_prices(tickers, a.since, px_path))
        result = {"note": "Research only, not investment advice.", "windows": {}}
        for d in (int(x) for x in a.days.split(",")):
            rows = attach_returns(obs, prices, d)
            result["windows"][str(d)] = summarize(rows)
            print(f"\n{d} trading days: {json.dumps(result['windows'][str(d)], indent=2)}")
        result["observations"] = [asdict(o) for o in attach_returns(obs, prices, 252)]
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    elif a.cmd == "research":
        from langgraph.types import Command

        from .agents.desk import Tools, build_desk
        from .agents.memory import Memory
        from .graph.temporal import TemporalGraph
        from .ingest.facts import FactStore
        from .ingest.releases import releases
        from .llm import chat
        from .retrieval.index import Filters

        if not settings.llm_api_key:
            raise SystemExit("LLM_API_KEY is not set (.env). Any OpenAI-compatible free tier "
                             "works, e.g. Groq or OpenRouter, or the Project 1 gateway.")
        idx = _load_index()
        tools = Tools(
            search=lambda q, as_of, ticker, k: idx.search(
                q, Filters(date.fromisoformat(as_of), (ticker,)), k=k),
            facts=FactStore(DATA / "facts.db"), graph=TemporalGraph(DATA / "graph.db"),
            memory=Memory(DATA / "memory.db"), human_in_loop=not a.auto,
            releases=lambda t, as_of: releases(EdgarClient(), t, as_of, DATA / "releases"))
        desk = build_desk(lambda system, user: chat([{"role": "system", "content": system},
                                                     {"role": "user", "content": user}]), tools)
        cfg = {"configurable": {"thread_id": f"{a.ticker}-{time.time()}"}}
        out = desk.invoke({"question": a.question, "ticker": a.ticker.upper(),
                           "as_of": a.as_of, "user": a.user}, cfg)
        while "__interrupt__" in out:
            req = out["__interrupt__"][0].value
            print(json.dumps(req, indent=2)[:3000])
            ans = input("approve [Enter] / type a JSON reply: ").strip()
            # never resume with {}: an empty resume value re-raises the interrupt
            out = desk.invoke(Command(resume=json.loads(ans) if ans else {"approve": True}), cfg)
        for t in out["trace"]:
            print(f"  {t['agent']:12} {t['secs']:>6}s  "
                  f"{ {k: v for k, v in t.items() if k not in ('agent', 'secs')} }")
        print("\n" + out["report"])
        if a.out:
            Path(a.out).write_text(out["report"], encoding="utf-8")

    elif a.cmd == "examiner-build":
        from .examiner.corpus import build

        stats = build(EdgarClient(), a.start, a.end, LETTERS, limit=a.limit)
        print(stats)

    elif a.cmd == "examiner-fetch":
        from .examiner.filings import fetch_all
        from .judge.cases import cases_from
        from .judge.harness import load_records

        cases = cases_from(load_records(LETTERS))
        print(f"{len(cases)} reviewed filings")
        print(fetch_all(EdgarClient(), cases, FILINGS))

    elif a.cmd == "examiner-embed":
        from .examiner.embed import embed_all
        from .examiner.filings import load
        from .judge.cases import cases_from
        from .judge.harness import load_records

        cases = cases_from(load_records(LETTERS))
        print(f"{len(cases)} filings to embed")
        print(embed_all(cases, lambda cid: load(FILINGS, cid), EMBEDS))

    elif a.cmd == "examiner-improve":
        from .examiner.improve import Registry, run
        from .judge.harness import load_records

        llm = None
        if not a.no_llm and settings.llm_api_key:
            from .llm import chat

            def llm(system: str, user: str) -> str:
                return chat([{"role": "system", "content": system},
                             {"role": "user", "content": user}])

        seed = None
        if a.seed:
            from .examiner.model import Recipe

            m = json.loads(a.seed.read_text(encoding="utf-8"))
            seed = (Recipe.from_dict(m["recipe"]), f"recipe carried over from {a.seed}")
        reg = Registry(MODELS)
        if a.code:
            from .examiner.improve import code_step

            if llm is None:
                raise SystemExit("--code needs LLM_API_KEY in .env (the LLM writes the code)")
            records = load_records(LETTERS)
            for _ in range(a.iterations):
                e = code_step(records, FILINGS, reg, llm)
                print(f"  {e.get('version')}: {e['decision']:8} sel_f1={e.get('selection_f1')} "
                      f"holdout_f1={e.get('holdout_f1')} | {e['reason']}")
            print("champion:", reg.state()["champion"])
            return
        reg = Registry(MODELS)
        for e in run(load_records(LETTERS), FILINGS, reg, a.iterations, llm=llm,
                     max_minutes=a.max_minutes, seed=seed):
            print(f"  {e.get('version')}: {e['decision']:8} sel_f1={e.get('selection_f1')} "
                  f"holdout_f1={e.get('holdout_f1')} | {e['reason']}")
        print("champion:", reg.state()["champion"])

    elif a.cmd == "examiner-status":
        from .examiner.improve import Registry

        reg = Registry(MODELS)
        s = reg.state()
        print("champion:", s["champion"], "| lineage:", " -> ".join(s["lineage"]) or "-")
        for e in reg.attempts()[-10:]:
            print(f"  {e['time']} {e.get('version')} from {e.get('parent')}: {e['decision']:8} "
                  f"sel={e.get('selection_f1')} hold={e.get('holdout_f1')} "
                  f"{json.dumps(e['changes'])[:80]} | {e['rationale'][:60]}")

    elif a.cmd == "examiner-rollback":
        from .examiner.improve import Registry

        print("champion now:", Registry(MODELS).rollback())

    elif a.cmd == "judge-seal":
        from .judge.harness import seal

        if not a.yes:
            raise SystemExit("Refusing: sealing accepts the current judge as the new yardstick. "
                             "Re-run with --yes only after a deliberate, reviewed judge change.")
        for name, h in seal().items():
            print(f"{h[:12]}  {name}")

    elif a.cmd == "judge-baselines":
        from .judge.baselines import BASELINES
        from .judge.harness import evaluate, load_records

        records = load_records(LETTERS)
        results = {}
        for name, fn in BASELINES.items():
            rep = evaluate(fn, records, test_from=a.test_from, k=a.k)
            results[name] = rep
            o = rep["overall"]
            print(f"{name:18} n={o['n']:5} precision@{a.k}={o['precision']:.3f} "
                  f"recall@{a.k}={o['recall']:.3f} f1={o['f1']:.3f} hit={o['hit_rate']:.3f}")
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    elif a.cmd == "eval-retrieval":
        from .retrieval.evaluate import evaluate, load_golden, to_markdown

        golden = load_golden(Path(a.golden))
        res = evaluate(_load_index(), golden, k=a.k)
        md = to_markdown(res, a.k, len(golden))
        print(md)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
