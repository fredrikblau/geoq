# e5vectortest.py  (LangChain 1.x compatible, no deprecated imports)
import torch
import re
import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document


# ------------------------------------------------------------------
# 1. Load DB & Embeddings
# ------------------------------------------------------------------
embeddings = SentenceTransformerEmbeddings(
    model_name="intfloat/multilingual-e5-large",
    encode_kwargs={"normalize_embeddings": True},
)
db = Chroma(persist_directory="qeshm_db", embedding_function=embeddings)

# Re-create LangChain Document objects from the persisted collection
raw = db._collection.get(include=["documents", "metadatas"])
docs = [
    Document(page_content=c, metadata=m)
    for c, m in zip(raw["documents"], raw["metadatas"])
]

# ------------------------------------------------------------------
# 2. Custom Hybrid Retriever (manual ensemble)
# ------------------------------------------------------------------
vector_retriever = db.as_retriever(search_kwargs={"k": 12})
bm25 = BM25Retriever.from_documents(docs)
bm25.k = 12


def weighted_hybrid_retriever(query: str, alpha: float = 0.7, k: int = 12):
    """Weighted fusion of vector and BM25 results."""
    vec_results = vector_retriever.invoke(query)
    bm25_results = bm25.invoke(query)

    # Give each result a normalized rank score
    vec_scores = {id(d): (1 - i / len(vec_results)) for i, d in enumerate(vec_results)}
    bm25_scores = {
        id(d): (1 - i / len(bm25_results)) for i, d in enumerate(bm25_results)
    }

    all_docs = {id(d): d for d in vec_results + bm25_results}.values()
    combined = []
    for d in all_docs:
        v = vec_scores.get(id(d), 0)
        b = bm25_scores.get(id(d), 0)
        score = alpha * v + (1 - alpha) * b
        combined.append((d, score))

    combined.sort(key=lambda x: x[1], reverse=True)
    return [d for d, _ in combined[:k]]


# ------------------------------------------------------------------
# 3. Reranker (sigmoid – correct for jina-reranker-v2)
# ------------------------------------------------------------------
MODEL_ID = "jinaai/jina-reranker-v2-base-multilingual"
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_ID, trust_remote_code=True, torch_dtype=torch.float16
)
model = model.to("cuda" if torch.cuda.is_available() else "cpu").eval()


def rerank(query: str, docs, top_k: int = 3):
    pairs = [[query, d.page_content] for d in docs]
    inputs = tokenizer(
        pairs, padding=True, truncation=True, return_tensors="pt", max_length=512
    ).to(model.device)

    with torch.no_grad():
        scores = model(**inputs).logits.squeeze(-1)
        probs = torch.sigmoid(scores).cpu().numpy()

    ranked = sorted(zip(docs, probs), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


# ------------------------------------------------------------------
# 4. Helpers
# ------------------------------------------------------------------
def extract_address(text):
    m = re.search(r"آدرس[:\s]+([^.\n]+)", text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else "مشخص نیست"


def confidence_label(score):
    if score > 0.7:
        return "قوی"
    if score > 0.5:
        return "خوب"
    return "شاید"


# ------------------------------------------------------------------
# 5. Test Query
# ------------------------------------------------------------------
def test_query(query):
    print(f"\nQuery: {query}\n")

    raw = weighted_hybrid_retriever(query, alpha=0.7)
    results = rerank(query, raw, top_k=3)

    for i, (doc, score) in enumerate(results, 1):
        name = doc.metadata["name"]
        cat = doc.metadata["category"]
        tags = doc.metadata.get("tags", "")
        addr = extract_address(doc.page_content)
        conf = confidence_label(score)

        print(f"{i}. [{conf}] {name}")
        print(f"   نوع: {cat} | تگ: {tags}")
        print(f"   آدرس: {addr}")
        print(f"   امتیاز: {score:.3f}")
        print("-" * 50)


# ------------------------------------------------------------------
# 6. Run
# ------------------------------------------------------------------
if __name__ == "__main__":
    queries = [
        "بیلیارد کجا بازی کنم؟",
        "کافه کجا برم؟",
        "کدوم کافه میشه سیگار کشید؟",
        "دستبند از کجا بخرم؟",
        "بولینگ کجا بازی کنم؟",
        "کجا قهوه صبح زود بخورم؟",
        "کافه با فضای بیرونی در قشم معرفی کن",
        "کافه تو طبل کجا هست؟",
        "کافه با ویو دریا چطور",
        "کافه برای عکاسی کجا هست؟",
    ]
    for q in queries:
        test_query(q)
