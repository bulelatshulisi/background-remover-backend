from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from rembg import remove, new_session
from PIL import Image
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from typing import List
import os

app = FastAPI(title="Background Remover API")
session = new_session("isnet-general-use")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173",
                    "http://127.0.0.1:5173",
        "https://background-remover-frontend-two.vercel.app",],  # later change this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check():
    return {"status": "Background remover API is running"}


@app.post("/remove-background")
async def remove_background(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file")

    try:
        image_bytes = await file.read()

        input_image = Image.open(BytesIO(image_bytes)).convert("RGBA")
        output_image = remove(input_image, session=session)

        output_buffer = BytesIO()
        output_image.save(output_buffer, format="PNG")
        output_buffer.seek(0)

        return Response(
            content=output_buffer.getvalue(),
            media_type="image/png",
            headers={
                "Content-Disposition": 'attachment; filename="background_removed.png"'
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove background: {str(e)}"
        )


@app.post("/remove-background/multiple")
async def remove_background_multiple(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Please upload at least one image")

    try:
        zip_buffer = BytesIO()

        with ZipFile(zip_buffer, "w", ZIP_DEFLATED) as zip_file:
            for index, file in enumerate(files, start=1):
                if not file.content_type or not file.content_type.startswith("image/"):
                    raise HTTPException(
                        status_code=400,
                        detail=f"{file.filename} is not an image file"
                    )

                image_bytes = await file.read()

                input_image = Image.open(BytesIO(image_bytes)).convert("RGBA")
                output_image = remove(input_image, session=session)

                image_output_buffer = BytesIO()
                output_image.save(image_output_buffer, format="PNG")
                image_output_buffer.seek(0)

                original_name = file.filename or f"image_{index}"
                name_without_extension = os.path.splitext(original_name)[0]
                output_filename = f"{name_without_extension}_background_removed.png"

                zip_file.writestr(
                    output_filename,
                    image_output_buffer.getvalue()
                )

        zip_buffer.seek(0)

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="background_removed_images.zip"'
            },
        )

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove backgrounds: {str(e)}"
        )