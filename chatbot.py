import os
import fitz
import chromadb
from google import genai
from prompt import CONTEXTO
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from io import BytesIO

# Cargar variables de entorno
load_dotenv()
API_KEY = os.getenv("API_KEY")

# Inicializar cliente Gemini
client = genai.Client(api_key=API_KEY)

# Modelo para embeddings
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

# Inicializar ChromaDB
# Aseguramos que el cliente y la colección se inicialicen solo una vez
try:
    chroma_client = chromadb.PersistentClient(path="./db")
    collection = chroma_client.get_or_create_collection(name="pdf_rag")
    print("📦 ChromaDB inicializado y colección 'pdf_rag' lista.")
except Exception as e:
    print(f"❌ Error al inicializar ChromaDB: {e}")
    # Considerar cómo manejar este error en la aplicación real

# Función para extraer texto de PDF desde bytes
def extract_text_from_pdf_bytes(pdf_bytes):
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf") # Abre el archivo PDF desde bytes
        text = "\n".join([page.get_text() for page in doc]) # Extrae el texto de cada página
        return text
    except Exception as e:
        print(f"❌ Error al extraer texto del PDF: {e}")
        return ""

# Función para dividir el texto en fragmentos
def chunk_text(text, chunk_size=500):
    words = text.split()
    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

# Procesar e indexar un PDF con un ID asociado
# Ahora recibe los bytes del PDF y un identificador único (ej: GridFS file_id)
def process_pdf_for_rag(pdf_bytes, file_id):
    print(f"⏳ Procesando PDF con ID: {file_id}")
    try:
        # Opcional: Eliminar chunks antiguos asociados a este file_id si ya existían
        # Esto es útil si se actualiza un producto con un nuevo PDF
        # Sin embargo, get() puede ser lento con muchos datos.
        # Una alternativa es almacenar los IDs de Chroma asociados a cada file_id en MongoDB
        # y eliminarlos directamente. Por simplicidad, omitimos la eliminación por ahora
        # a menos que sea una re-indexación explícita.
        # Si necesitas re-indexar, tendrías que buscar los IDs de Chroma por metadato {"file_id": file_id} y borrarlos.
        
        text = extract_text_from_pdf_bytes(pdf_bytes)
        if not text:
            print(f"⚠️ No se pudo extraer texto del PDF ID: {file_id}")
            return False

        chunks = chunk_text(text)
        if not chunks:
            print(f"⚠️ No se crearon chunks para el PDF ID: {file_id}")
            return False

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            try:
                embedding = embed_model.encode(chunk).tolist()
                ids.append(f"{file_id}_{i}") # ID único combinando file_id y chunk index
                embeddings.append(embedding)
                documents.append(chunk)
                metadatas.append({"file_id": str(file_id)}) # Asociar metadato file_id
            except Exception as e:
                print(f"❌ Error al crear embedding para chunk {i} de {file_id}: {e}")
                # Decidir si continuar o fallar

        if ids: # Solo agregar si hay chunks procesados
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas # Añadir metadatos
            )
            print(f"✅ PDF ID {file_id} indexado correctamente en ChromaDB.")
            return True
        else:
             print(f"⚠️ No hay chunks válidos para indexar para PDF ID: {file_id}")
             return False

    except Exception as e:
        print(f"❌ Error general al procesar PDF ID {file_id}: {e}")
        return False


# Función para responder preguntas en base a un PDF específico
# Ahora recibe la pregunta Y el identificador del PDF (file_id)
def query_pdf_rag(question, file_id):
    print(f"❓ Pregunta sobre PDF ID {file_id}: {question}")
    try:
        embedding = embed_model.encode(question).tolist()

        # Busca lo más relevante, FILTRANDO por el metadato file_id
        results = collection.query(
            query_embeddings=[embedding],
            n_results=3, # Número de chunks relevantes
            where={"file_id": str(file_id)} # Filtra por el ID del archivo
        )

        # Extraer contexto relevante
        context = "\n\n".join(results["documents"][0]) if results and results["documents"] and results["documents"][0] else "No encontré información relevante en la ficha técnica de este producto."

        # Enviar a Gemini el prompt general + contexto específico
        prompt_with_context = f"{CONTEXTO}\n\nContexto de la ficha técnica:\n{context}\n\nPregunta: {question}"

        # Genera la respuesta de Gemini
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-04-17",
            contents=prompt_with_context,
        )
        print(f"🤖 Respuesta de Gemini recibida para PDF ID {file_id}.")
        return response.text

    except Exception as e:
        print(f"❌ Error al consultar RAG para PDF ID {file_id}: {e}")
        # Devolver un mensaje amigable en caso de error
        return "Lo siento, ocurrió un error al procesar tu solicitud."


# El bloque if __name__ == "__main__": es solo para pruebas locales de chatbot.py
# No se ejecutará cuando se importe en main.py
if __name__ == "__main__":
    print("Ejecutando prueba local de chatbot.py (no se usa en la aplicación web principal)")
    # Ejemplo de cómo podrías usarlo para indexar un archivo local y preguntar
    # Esto es solo para depuración de la lógica RAG individual
    # pdf_test_path = "pdf/Zephyrus_G14.pdf" # Asegúrate de tener este archivo
    # try:
    #     with open(pdf_test_path, "rb") as f:
    #         pdf_bytes_test = f.read()
    #     test_file_id = "test_local_pdf_123"
    #     process_pdf_for_rag(pdf_bytes_test, test_file_id)
    #     while True:
    #         question = input("Pregunta (o 'salir'): ")
    #         if question.lower() == "salir":
    #             print("Chat finalizado")
    #             break
    #         response = query_pdf_rag(question, test_file_id)
    #         print("Respuesta:", response)
    # except FileNotFoundError:
    #     print(f"Error: Archivo {pdf_test_path} no encontrado.")
    # except Exception as e:
    #      print(f"Ocurrió un error durante la prueba: {e}")