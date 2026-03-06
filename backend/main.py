from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from database import SessionLocal, Document, User
from auth import (
    get_password_hash, 
    authenticate_user, 
    create_access_token, 
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from datetime import timedelta
from pydantic import BaseModel
import shutil
import PyPDF2
import os
from fastapi.middleware.cors import CORSMiddleware
import requests as http_requests

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads", exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def extract_text_from_pdf(file_path):
    text = ""
    with open(file_path, "rb") as file:
        pdf = PyPDF2.PdfReader(file)
        for page in pdf.pages:
            text += page.extract_text()
    return text

# Routes
# Auth endpoints
@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@app.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/")
def home():
    return {"message": "Knowledge Base API"}

@app.get("/search")
def search_documents(q: str, db: Session = Depends(get_db)):
    docs = db.query(Document).filter(
        Document.content_text.like(f'%{q}%')
    ).all()
    return docs

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...), 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    file_path = f"uploads/{file.filename}"
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    content_text = None
    if file.filename.endswith('.pdf'):
        content_text = extract_text_from_pdf(file_path)
    
    doc = Document(
        user_id=current_user.id,  
        filename=file.filename,
        file_path=file_path,
        file_size=os.path.getsize(file_path),
        content_text=content_text
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    return {
        "id": doc.id,
        "filename": doc.filename,
        "text_preview": content_text[:200] if content_text else None
    }

@app.get("/documents")
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  
):
    docs = db.query(Document).filter(Document.user_id == current_user.id).all() 

@app.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"error": "Document not found"}
    
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    
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

@app.post("/documents/{doc_id}/ask")
async def ask_question(doc_id: int, question: str, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return {"error": "Document not found"}
    
    if not doc.content_text:
        return {"error": "No text content available for this document"}
    
    try:
        response = http_requests.post('http://localhost:11434/api/generate', json={
            "model": "llama3.2",
            "prompt": f"""You are a helpful assistant that answers questions based ONLY on the provided document content.

Document Content:
{doc.content_text}

Question: {question}

Answer based only on the information in the document above:""",
            "stream": False,
            "options": {
                "temperature": 0.7,
                "num_predict": 500
            }
        })
        
        result = response.json()
        answer = result.get('response', 'No response generated')
        
        return {
            "question": question,
            "answer": answer,
            "document": doc.filename,
            "model": "llama3.2 (local)"
        }
    
    except Exception as e:
        return {"error": f"AI request failed: {str(e)}"}