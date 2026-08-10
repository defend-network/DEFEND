from __future__ import annotations

from rag_store import get_or_create_table

DOC = "doc_27df51c1baea47bb"
NEEDLES = ["table 13", "table13", "table  13", "tble 13", "tabl e 13"]


def main():
    table = get_or_create_table()
    # Pull a wide slice for this document
    rows = (
        table.search()
        .where(f"document_id = '{DOC}'")
        .limit(5000)
        .to_list()
    )
    print(f"total rows fetched for doc: {len(rows)}")

    hits = []
    for r in rows:
        text = (r.get("text") or "")
        low = text.lower().replace("\n", " ")
        if any(n in low for n in NEEDLES) or ("tabl" in low and "13" in low):
            hits.append(r)

    print(f"needle hits: {len(hits)}")
    for i, r in enumerate(hits[:30]):
        text = (r.get("text") or "").replace("\n", " ")
        print("=" * 60)
        print(f"[{i}] page={r.get('page')} chunk_index={r.get('chunk_index')} id={r.get('chunk_id')}")
        print(text[:500])

    # Also show page 25 chunks specifically
    page25 = [r for r in rows if r.get("page") == 25]
    print("\n" + "#" * 60)
    print(f"page 25 chunks: {len(page25)}")
    for i, r in enumerate(page25[:10]):
        text = (r.get("text") or "").replace("\n", " ")
        print("-" * 40)
        print(f"[{i}] {text[:400]}")


if __name__ == "__main__":
    main()