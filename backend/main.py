from fastapi import FastAPI, UploadFile, File, Depends
from sqlalchemy.orm import Session
from database import SessionLocal, Document
import shutil
import PyPDF2
import os
from fastapi.middleware.cors import CORSMiddleware

# Create FastAPI app FIRST
app = FastAPI()

# Create uploads folder if it doesn't exist
os.makedirs("uploads", exist_ok=True)

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper function
def extract_text_from_pdf(file_path):
    text = ""
    with open(file_path, "rb") as file:
        pdf = PyPDF2.PdfReader(file)
        for page in pdf.pages:
            text += page.extract_text()
    return text

# Routes
@app.get("/")
def home():
    return {"message": "Knowledge Base API"}

@app.get("/search")
def search_documents(q: str, db: Session = Depends(get_db)):
    # Simple keyword search in content_text
    docs = db.query(Document).filter(
        Document.content_text.like(f'%{q}%')
    ).all()
    
    return docs

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_path = f"uploads/{file.filename}"
    
    # Save file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Extract text if PDF
    content_text = None
    if file.filename.endswith('.pdf'):
        content_text = extract_text_from_pdf(file_path)
    
    # Save to database
    doc = Document(
        filename=file.filename,
        file_path=file_path,
        file_size=file.size,
        content_text=content_text
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)  # Get the ID that was assigned
    
    return {
        "id": doc.id,
        "filename": doc.filename,
        "text_preview": content_text[:200] if content_text else None
    }

@app.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).all()
    return docs

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"error": "Document not found"}
    
    # Delete file from disk
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    
    # Delete from database
    db.delete(doc)
    db.commit()
    
    return {"message": "Document deleted successfully"}

@app.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"error": "Document not found"}
    return doc

@app.get("/documents/{doc_id}/content")
def get_document_content(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"error": "Document not found"}
    
    return {
        "id": doc.id,
        "filename": doc.filename,
        "content": doc.content_text
    }

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)