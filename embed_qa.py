# embed_qa.py
import json
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import SentenceTransformerEmbeddings
import os

# ------------------------------------------------------------------
# 1. Load QA data
# ------------------------------------------------------------------
with open("qa_qeshm.json", "r", encoding="utf-8") as f:
    qa_list = json.load(f)

print(f"Loaded {len(qa_list)} QA pairs")

# ------------------------------------------------------------------
# 2. Create Documents (question + answer in content, metadata preserved)
# ------------------------------------------------------------------
docs = []
for item in qa_list:
    # Combine question + answer for rich semantic context
    try:
        item["question"]
    except:
        print(item)
    content = f"سوال: {item['question']}\nپاسخ: {item['answer']}"

    metadata = {
        "id": item["id"],
        "question": item["question"],
        "answer": item["answer"],
        "category": item["category"],
        "tags": ", ".join(item["tags"]),
        "source": item["id"],
    }

    docs.append(Document(page_content=content, metadata=metadata))

# ------------------------------------------------------------------
# 3. Choose Embedding Model (Hakim = BEST for Farsi)
# ------------------------------------------------------------------
# Option A: Hakim (SOTA Persian) — use if available
# MODEL_NAME = "MCINext/Hakim"

# Option B: multilingual-e5-large (excellent fallback)
MODEL_NAME = "intfloat/multilingual-e5-large"

embeddings = SentenceTransformerEmbeddings(
    model_name=MODEL_NAME, encode_kwargs={"normalize_embeddings": True}
)

# ------------------------------------------------------------------
# 4. Create / Update Chroma DB
# ------------------------------------------------------------------
DB_PATH = "qeshm_db"

# Optional: delete old DB
# import shutil; shutil.rmtree(DB_PATH, ignore_errors=True)

db = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)
db.add_documents(docs)
db.persist()

print(f"Embedded {len(docs)} QA pairs into '{DB_PATH}' using {MODEL_NAME}")
