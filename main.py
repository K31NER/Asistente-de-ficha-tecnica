# FILE: main.py

from fastapi.responses import HTMLResponse,RedirectResponse,Response, JSONResponse
from fastapi import FastAPI,Form,Request,UploadFile,HTTPException,File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from bson.objectid import ObjectId
from pymongo import MongoClient
# Importar ConfigDict para Pydantic v2+
from pydantic import BaseModel, ConfigDict # <--- Añadir ConfigDict
from gridfs import GridFS
import uvicorn
import os
from chatbot import process_pdf_for_rag, query_pdf_rag
from io import BytesIO # Necesario si lees de UploadFile antes de GridFS

#Inicializamos la api
app = FastAPI()

#definimos la ruta de las plantillas
templates = Jinja2Templates(directory="templates")

# Agrega esta línea para montar el directorio estático
app.mount("/static", StaticFiles(directory="static"), name="static")

# Conexion a la base de datos
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
try:
    client = MongoClient(MONGO_URI)
    db = client["Tecnomack"] # Nombre de la base de datos
    collection = db["productos"] # Nombre de la coleccion("tabla")
    fs = GridFS(db)
    client.admin.command('ping')
    print("📦 Conexión a MongoDB exitosa!")
except Exception as e:
    print(f"❌ Error al conectar a MongoDB: {e}")
    # Considerar un manejo de errores más robusto aquí

# creamos la estructura de la coleccion
class Producto(BaseModel):
    nombre:str
    precio:str
    # NOTA: Estos campos representan cómo se guarda en DB (ObjectId de GridFS),
    # no cómo se reciben en el formulario (UploadFile).
    imagen: ObjectId
    descripcion:str
    categoria:str
    ficha_tecnica: ObjectId

    # Configuración para permitir tipos arbitrarios como ObjectId
    # Esto le dice a Pydantic que no intente validar o crear un esquema detallado para ObjectId
    model_config = ConfigDict(arbitrary_types_allowed=True) # <--- Añadir esta línea

# creamos los endpoints de renderizado
@app.get("/", response_class=HTMLResponse, tags=["Renderizado"])
async def inicio(request: Request):
    categorias = collection.distinct("categoria")
    productos_por_categoria = {}

    for categoria in categorias:
        productos = list(collection.find({"categoria": categoria}))

        # Convertir ObjectIds y crear URLs
        for producto in productos:
            # Asegurarse de que los campos ObjectId existen antes de convertirlos
            producto["_id"] = str(producto.get("_id")) # Convertir ObjectId a string
            imagen_id = producto.get("imagen")
            ficha_tecnica_id = producto.get("ficha_tecnica")

            producto["imagen_url"] = f"/imagen/{str(imagen_id)}" if imagen_id else "#" # Usar # o una imagen por defecto si no hay ID
            producto["ficha_url"] = f"/pdf/{str(ficha_tecnica_id)}" if ficha_tecnica_id else "#" # Usar # o deshabilitar el enlace si no hay ID

        productos_por_categoria[categoria] = productos

    return templates.TemplateResponse("index.html", {
        "request": request,
        "productos_por_categoria": productos_por_categoria
    })

@app.get("/form",response_class=HTMLResponse,tags=["Renderizado"])
def formulario(request:Request):
    return templates.TemplateResponse("form.html",{"request":request})

@app.get("/chat",response_class=HTMLResponse,tags=["Renderizado"])
def chat_page(request:Request, product_id: str = None): # Aceptar product_id
    return templates.TemplateResponse("chatbot.html",{"request":request, "product_id": product_id}) # Pasar product_id al template

#Creamos los endpoints de funcionalidades
@app.post("/formulario",tags=["Funcionalidades"])
async def create_product(
    request:Request,
    nombre:str=Form(...),
    precio:str=Form(...),
    imagen:UploadFile=File(...),
    descripcion:str=Form(...),
    categoria:str=Form(...),
    ficha_tecnica:UploadFile=File(...)
):
    imagen_id = None
    ficha_tecnica_id = None
    try:
        if not imagen.filename or not ficha_tecnica.filename:
             raise HTTPException(status_code=400, detail="Debe subir una imagen y una ficha técnica.")

        # guardamos la imagen
        imagen_bytes = await imagen.read()
        imagen_id = fs.put(imagen_bytes ,filename=imagen.filename, content_type=imagen.content_type)

        # guardamos la ficha tecnica
        ficha_bytes = await ficha_tecnica.read() # Leer bytes antes de guardarlos
        ficha_tecnica_id = fs.put(ficha_bytes,filename=ficha_tecnica.filename, content_type=ficha_tecnica.content_type)

        # creamos un diccionario con los datos
        data = {
            "nombre":nombre,
            "precio":precio,
            "imagen":imagen_id, # ObjectId
            "descripcion":descripcion,
            "categoria":categoria,
            "ficha_tecnica":ficha_tecnica_id # ObjectId
        }
        inserted_result = collection.insert_one(data)
        product_id = inserted_result.inserted_id # ObjectId del producto

        # --- Procesar la ficha técnica para RAG ---
        print(f"Iniciando procesamiento RAG para ficha técnica {ficha_tecnica_id} del producto {product_id}")
        # Usar los bytes que ya leímos
        success = process_pdf_for_rag(ficha_bytes, str(ficha_tecnica_id)) # Usar el ID de GridFS como identificador RAG (convertido a string)

        if not success:
            print(f"⚠️ Advertencia: No se pudo indexar la ficha técnica {ficha_tecnica_id} para RAG.")
            # Decide aquí si quieres que esto sea un error o solo una advertencia.
            # Por ahora, el producto se guarda igual.

        return RedirectResponse(url="/",status_code=303) # 303 See Other es estándar para POST + Redirect
    except HTTPException as e:
        raise e # Re-lanzar errores HTTP personalizados
    except Exception as e:
        print(f"❌ Error inesperado al guardar el producto o procesar PDF: {e}")
        # Limpiar archivos de GridFS si algo falló después de guardarlos
        if imagen_id and fs.exists(imagen_id):
             fs.delete(imagen_id)
        if ficha_tecnica_id and fs.exists(ficha_tecnica_id):
             fs.delete(ficha_tecnica_id)
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {e}")
    finally:
        # Cerrar los archivos UploadFile (aunque ya leímos los bytes)
        await imagen.close()
        await ficha_tecnica.close()


# Nuevo endpoint para manejar las consultas del chatbot
class ChatRequest(BaseModel):
    product_id: str # Recibimos el ID del producto como string
    question: str

@app.post("/api/chat", tags=["Funcionalidades"])
async def chat_with_product(chat_request: ChatRequest):
    product_id_str = chat_request.product_id
    question = chat_request.question

    try:
        # Buscar el producto para obtener el ID de la ficha técnica (ObjectId)
        # Convertir el string product_id de vuelta a ObjectId para buscar en MongoDB
        product = collection.find_one({"_id": ObjectId(product_id_str)})
        if not product:
            raise HTTPException(status_code=404, detail="Producto no encontrado.")

        ficha_tecnica_id = product.get("ficha_tecnica") # Esto es un ObjectId
        if not ficha_tecnica_id:
             # Si el producto no tiene ficha técnica asociada en DB
             return JSONResponse(content={"response": "Lo siento, este producto no tiene una ficha técnica asociada para chatear."}, status_code=200)


        # Llamar a la función RAG
        # Pasamos el ID de GridFS de la ficha técnica (convertido a string para ChromaDB)
        bot_response = query_pdf_rag(question, str(ficha_tecnica_id))

        return JSONResponse(content={"response": bot_response})

    except Exception as e:
        print(f"❌ Error en endpoint /api/chat: {e}")
        raise HTTPException(status_code=500, detail="Error al comunicarse con el asistente.")


# Endpoint para obtener imágenes
@app.get("/imagen/{file_id}", tags=["Archivos"])
async def get_imagen(file_id: str):
    try:
        # Convertir el string file_id a ObjectId
        oid = ObjectId(file_id)
        if not fs.exists(oid):
             raise HTTPException(status_code=404, detail="Archivo de imagen no encontrado.")
        file = fs.get(oid)
        content_type = file.content_type if file.content_type else "image/jpeg"
        return Response(content=file.read(), media_type=content_type)
    except Exception as e:
        print(f"❌ Error al obtener imagen {file_id}: {e}")
        raise HTTPException(status_code=404, detail="Archivo no encontrado o ID inválido.")

# Endpoint para descargar archivos
@app.get("/pdf/{file_id}", tags=["Archivos"])
async def descargar_ficha_tecnica(file_id: str):
    try:
        # Convertir el string file_id a ObjectId
        oid = ObjectId(file_id)
        if not fs.exists(oid):
             raise HTTPException(status_code=404, detail="Archivo PDF no encontrado.")
        file = fs.get(oid)
        response = Response(content=file.read(), media_type="application/pdf")
        response.headers["Content-Disposition"] = f"attachment; filename={file.filename}"
        return response
    except Exception as e:
        print(f"❌ Error al descargar PDF {file_id}: {e}")
        raise HTTPException(status_code=404, detail="Archivo no encontrado o ID inválido.")


if __name__ == "__main__":
    # ejecutamos el servidor directamente con codigo
    uvicorn.run(app, host="127.0.0.1", port=8000)