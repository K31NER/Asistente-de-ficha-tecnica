from fastapi.responses import HTMLResponse,RedirectResponse,Response
from fastapi import FastAPI,Form,Request,UploadFile,HTTPException,File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles 
from bson.objectid import ObjectId
from pymongo import MongoClient
from pydantic import BaseModel
from gridfs import GridFS
import uvicorn
import os

#Inicializamos la api
app = FastAPI()

#definimos la ruta de las plantillas
templates = Jinja2Templates(directory="templates")

# Agrega esta línea para montar el directorio estático
app.mount("/static", StaticFiles(directory="static"), name="static")

#Conexion a la base de datos
client = MongoClient('localhost', 27017) #conexion a la base de datos
db = client["Tecnomack"] # Nombre de la base de datos
collection = db["productos"] # Nombre de la coleccion("tabla")
fs = GridFS(db)

#creamos la estructura de la coleccion
class Producto(BaseModel):
    nombre:str
    precio:str
    imagen:UploadFile
    descripcion:str
    categoria:str
    ficha_tecnica:UploadFile

#creamos los endpoints de renderizado
@app.get("/", response_class=HTMLResponse, tags=["Renderizado"])
async def inicio(request: Request):
    # Obtener todas las categorías únicas
    categorias = collection.distinct("categoria")
    
    productos_por_categoria = {}
    
    for categoria in categorias:
        productos = list(collection.find({"categoria": categoria}))
        
        # Convertir ObjectIds y crear URLs
        for producto in productos:
            producto["_id"] = str(producto["_id"])
            producto["imagen_url"] = f"/imagen/{str(producto['imagen'])}"
            producto["ficha_url"] = f"/pdf/{str(producto['ficha_tecnica'])}"
        productos_por_categoria[categoria] = productos
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "productos_por_categoria": productos_por_categoria
    })

@app.get("/form",response_class=HTMLResponse,tags=["Renderizado"])
def formulario(request:Request):
    return templates.TemplateResponse("form.html",{"request":request})

#Creamos los endpoints de funcionalidades
@app.post("/formulario",tags=["Funcionalidades"])
async def formulario(request:Request,
                nombre:str=Form(...),
                precio:str=Form(...),
                imagen:UploadFile=File(...),
                descripcion:str=Form(...),
                categoria:str=Form(...),
                ficha_tecnica:UploadFile=File(...)):
        
    try:
        #guardamos la imagen
        imagen_bytes = await imagen.read()
        imagen_id = fs.put(imagen_bytes ,filename=imagen.filename)
        
        #guardamos la ficha tecnica
        ficha_bytes = await ficha_tecnica.read()
        ficha_tecnica_id = fs.put(ficha_bytes,filename=ficha_tecnica.filename)
        
        #creamos un diccionario con los datos 
        data = {
            "nombre":nombre,
            "precio":precio,
            "imagen":imagen_id,
            "descripcion":descripcion,
            "categoria":categoria,
            "ficha_tecnica":ficha_tecnica_id
        }
        collection.insert_one(data)
        return RedirectResponse(url="/",status_code=302)
    except :
        raise HTTPException(status_code=404,detail="Error al guardar los datos")
    finally:
        #cramos los archivos
        await ficha_tecnica.close()
        await imagen.close()


# Endpoint para obtener imágenes
@app.get("/imagen/{file_id}", tags=["Archivos"])
async def get_imagen(file_id: str):
    try:
        file = fs.get(ObjectId(file_id))
        return Response(content=file.read(), media_type="image/jpeg")
    except:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
if __name__ == "__main__":
    #ejecutaos el servidor directamente con codigo
    uvicorn.run(app, host="127.0.0.1", port=8000)
    
    