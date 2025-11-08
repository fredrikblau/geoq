import os, json
from dotenv import load_dotenv

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_community.embeddings import SentenceTransformerEmbeddings

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

f = open("dbf.json")
docs = json.load(f)
print(docs)

docs = [Document(page_content=str(d["description"]), metadata=d) for d in docs]

# ✅ embeddings
embeddings = SentenceTransformerEmbeddings(model_name="intfloat/multilingual-e5-large")

# ✅ Chunk docs AFTER cleaning (better RAG quality)
splitter = RecursiveCharacterTextSplitter(chunk_size=384, chunk_overlap=100)
chunks = splitter.split_documents(docs)

print(f"📦 Total chunks:", len(chunks))

# ❌ Remove empty chunks
chunks = [c for c in chunks if c.page_content.strip()]
if not chunks:
    raise Exception("All chunks empty — cleaning may be too strict.")

# ✅ Save to Chroma
db = Chroma.from_documents(
    documents=chunks, embedding=embeddings, persist_directory="qeshm_db"
)
db.persist()

print("🎉 HTML successfully cleaned & indexed!")
