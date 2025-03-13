import os
import fitz
import chromadb
from google import genai
from prompt import CONTEXTO
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# Cargar variables de entorno
load_dotenv()
API_KEY = os.getenv("API_KEY")

# Inicializar cliente Gemini
client = genai.Client(api_key=API_KEY)

# Modelo para embeddings
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

# Inicializar ChromaDB
chroma_client = chromadb.PersistentClient(path="./db")
collection = chroma_client.get_or_create_collection(name="pdf_rag")

# Función para extraer texto de PDF
def extract_text_from_pdf(pdf_path):
    doc = fitz.open(pdf_path)  # Abre el archivo PDF
    text = "\n".join([page.get_text() for page in doc])  # Extrae el texto de cada página y lo separa con un salto de línea por página
    return text

# Función para dividir el texto en fragmentos
def chunk_text(text, chunk_size=500):
    words = text.split()  # Vuelve el texto una lista de palabras
    # Toma bloques de 500 palabras y las vuelve string
    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

# Procesar e indexar un PDF
def process_pdf(pdf_path):
    # Obtener los IDs almacenados en la base de datos
    stored_ids = collection.get()["ids"]
    
    # Si hay datos en la base de datos, eliminarlos
    if stored_ids:
        collection.delete(ids=stored_ids)
    text = extract_text_from_pdf(pdf_path)  # Obtenemos el texto del documento
    chunks = chunk_text(text)  # Lo volvemos chunks de 500

    for i, chunk in enumerate(chunks):
        embedding = embed_model.encode(chunk).tolist()  # Se vuelve embedding
        collection.add(
            ids=[f"{pdf_path}_{i}"], 
            embeddings=[embedding], 
            documents=[chunk]
        )  # Se guarda en la base de datos
    print(f"📄 {pdf_path} indexado correctamente")

# Función para responder preguntas en base al PDF
def query_pdf(question):
    embedding = embed_model.encode(question).tolist()  # Volvemos la pregunta un vector
    results = collection.query(query_embeddings=[embedding], n_results=3)  # Busca lo más relevante 

    # Extraer contexto relevante
    context = "\n\n".join(results["documents"][0]) if results["documents"] else "No encontré información relevante en el PDF."

    # Enviar a Gemini el prompt general
    prompt = CONTEXTO
    
    # Genera la respuesta de Gemini
    response = client.models.generate_content(
        # Definimos el modelo a usar
        model="gemini-1.5-flash-latest", 
        # Definimos el mensaje que recibe Gemini que es prompt principal más el contexto fundamental 
        # Y por último la pregunta 
        contents=f"{prompt}\n\nContexto:\n{context}\n\nPregunta: {question}",
    )
    return response.text  # Devolvemos la respuesta 

# ---- Ejemplo de uso ----
if __name__ == "__main__":
    pdf_path = "pdf/Zephyrus_G14.pdf"
    process_pdf(pdf_path)  # Indexa el PDF
    while True:
        question = input("Pregunta: ")
        if question.lower() == "salir":
            print("Chat finalizado")
            break
        print(query_pdf(question))  # Responde en base al PDF
