import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from langchain_community.vectorstores import Chroma

# -----------------------------
# Load Embeddings
# -----------------------------
from langchain_community.embeddings import SentenceTransformerEmbeddings

embeddings = SentenceTransformerEmbeddings(
    model_name="intfloat/multilingual-e5-large",
    # The wrapper will automatically normalize when you pass this flag
    encode_kwargs={"normalize_embeddings": True},
)

# -----------------------------
# Load Vector DB
# -----------------------------
db = Chroma(embedding_function=embeddings, persist_directory="qeshm_db")

# -----------------------------
# Load Reranker (multilingual incl. Persian)
# -----------------------------
MODEL_ID = "jinaai/jina-reranker-v2-base-multilingual"

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_ID, trust_remote_code=True, torch_dtype=torch.float16
)
model.eval()


# -----------------------------
# Rerank Function
# -----------------------------
def rerank(query: str, docs, top_k: int = 3):
    texts = [d.page_content for d in docs]
    inputs = tokenizer(
        [query] * len(texts), texts, padding=True, truncation=True, return_tensors="pt"
    )

    with torch.no_grad():
        scores = model(**inputs).logits.squeeze(-1)
        scores = torch.softmax(scores, dim=0).tolist()

    # Sort docs by score descending
    ranked_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ranked_docs = [(docs[i], scores[i]) for i in ranked_idx[:top_k]]
    return ranked_docs


# -----------------------------
# Query & Test
# -----------------------------
def test_query(query):
    print(f"\n🔎 Query: {query}\n")

    # Step 1: Initial Vector Retrieval
    raw = db.similarity_search(query, k=8)

    # Step 2: Rerank
    results = rerank(query, raw, top_k=3)

    # Step 3: Display Results
    for i, (doc, score) in enumerate(results, 1):
        print(f"🏆 Rank {i} | Score: {round(score,3)} | {doc.metadata.get('name')}")
        print(doc.page_content[:300], "...")
        print(f"📍 Type: {doc.metadata.get('type')}")
        print("-" * 60)


# -----------------------------
# Run Tests
# -----------------------------
if __name__ == "__main__":
    queries = [
        "بیلیارد کجا بازی کنم؟",
        "کافه کجا برم؟",
        "کدوم کافه میشه سیگار کشید؟",
        "دستبند از کجا بخرم؟",
        "بولینگ کجا بازی کنم؟",
        "کجا قهوه صبح زود بخورم؟",
        "بازار الماس چطور؟",
        "کجا میتونم اکسسوری و ماگ بخرم؟",
        "کافه با فضای بیرونی در قشم معرفی کن",
        "کافه تو سلخ میخوام",
        "تو طبل کافه کجا هست؟",
        "کافه با ویو دریا چطور",
        "کافه برای عکاسی کجا هست؟",
    ]

    for q in queries:
        test_query(q)
