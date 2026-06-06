from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from rembg import remove, new_session
from PIL import Image
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from typing import List
import os
import logging
import time
import uuid
import traceback

# ---------------------------------------------------------
# Logging setup
# ---------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("background-remover-api")


def format_bytes(size_in_bytes: int) -> str:
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"

    if size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.2f} KB"

    return f"{size_in_bytes / (1024 * 1024):.2f} MB"


app = FastAPI(title="Background Remover API")

logger.info("Starting Background Remover API")
logger.info("Loading rembg model session: isnet-general-use")

session = new_session("isnet-general-use")

logger.info("Model session loaded successfully")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://background-remover-frontend-two.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------

@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info(
        f"[{request_id}] Incoming request | "
        f"method={request.method} | "
        f"path={request.url.path} | "
        f"client={request.client.host if request.client else 'unknown'}"
    )

    try:
        response = await call_next(request)

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[{request_id}] Request completed | "
            f"status={response.status_code} | "
            f"duration={duration_ms:.2f}ms"
        )

        return response

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            f"[{request_id}] Request crashed | "
            f"duration={duration_ms:.2f}ms | "
            f"error={str(e)}"
        )
        logger.error(traceback.format_exc())

        raise


@app.get("/")
def health_check():
    logger.info("Health check requested")
    return {"status": "Background remover API is running"}


# ---------------------------------------------------------
# Single image endpoint
# ---------------------------------------------------------

@app.post("/remove-background")
async def remove_background(file: UploadFile = File(...)):
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info(f"[{request_id}] Single image background removal started")

    if not file:
        logger.warning(f"[{request_id}] No file received")
        raise HTTPException(status_code=400, detail="Please upload an image file")

    logger.info(
        f"[{request_id}] File received | "
        f"filename={file.filename} | "
        f"content_type={file.content_type}"
    )

    if not file.content_type or not file.content_type.startswith("image/"):
        logger.warning(
            f"[{request_id}] Invalid file type | "
            f"filename={file.filename} | "
            f"content_type={file.content_type}"
        )
        raise HTTPException(status_code=400, detail="Please upload an image file")

    try:
        logger.info(f"[{request_id}] Reading uploaded image bytes")

        image_bytes = await file.read()

        logger.info(
            f"[{request_id}] Image bytes read | "
            f"filename={file.filename} | "
            f"size={format_bytes(len(image_bytes))}"
        )

        logger.info(f"[{request_id}] Opening image with PIL")

        input_image = Image.open(BytesIO(image_bytes)).convert("RGBA")

        logger.info(
            f"[{request_id}] Image opened successfully | "
            f"mode={input_image.mode} | "
            f"width={input_image.width} | "
            f"height={input_image.height}"
        )

        logger.info(f"[{request_id}] Running background removal model")

        model_start_time = time.time()
        output_image = remove(input_image, session=session)
        model_duration_ms = (time.time() - model_start_time) * 1000

        logger.info(
            f"[{request_id}] Background removal completed | "
            f"duration={model_duration_ms:.2f}ms"
        )

        logger.info(f"[{request_id}] Saving output image as PNG")

        output_buffer = BytesIO()
        output_image.save(output_buffer, format="PNG")
        output_buffer.seek(0)

        output_size = len(output_buffer.getvalue())

        logger.info(
            f"[{request_id}] Output image created | "
            f"output_size={format_bytes(output_size)}"
        )

        total_duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[{request_id}] Single image request successful | "
            f"total_duration={total_duration_ms:.2f}ms"
        )

        return Response(
            content=output_buffer.getvalue(),
            media_type="image/png",
            headers={
                "Content-Disposition": 'attachment; filename="background_removed.png"'
            },
        )

    except Exception as e:
        total_duration_ms = (time.time() - start_time) * 1000

        logger.error(
            f"[{request_id}] Single image request failed | "
            f"filename={file.filename} | "
            f"duration={total_duration_ms:.2f}ms | "
            f"error={str(e)}"
        )
        logger.error(traceback.format_exc())

        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove background: {str(e)}"
        )


# ---------------------------------------------------------
# Multiple image endpoint
# ---------------------------------------------------------

@app.post("/remove-background/multiple")
async def remove_background_multiple(files: List[UploadFile] = File(...)):
    request_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    logger.info(f"[{request_id}] Multiple image background removal started")

    if not files:
        logger.warning(f"[{request_id}] No files received")
        raise HTTPException(status_code=400, detail="Please upload at least one image")

    logger.info(f"[{request_id}] Files received | count={len(files)}")

    try:
        zip_buffer = BytesIO()

        total_input_bytes = 0
        total_output_bytes = 0
        processed_count = 0

        logger.info(f"[{request_id}] Creating ZIP file in memory")

        with ZipFile(zip_buffer, "w", ZIP_DEFLATED) as zip_file:
            for index, file in enumerate(files, start=1):
                file_start_time = time.time()

                logger.info(
                    f"[{request_id}] Processing file {index}/{len(files)} | "
                    f"filename={file.filename} | "
                    f"content_type={file.content_type}"
                )

                if not file.content_type or not file.content_type.startswith("image/"):
                    logger.warning(
                        f"[{request_id}] Invalid file type | "
                        f"filename={file.filename} | "
                        f"content_type={file.content_type}"
                    )

                    raise HTTPException(
                        status_code=400,
                        detail=f"{file.filename} is not an image file"
                    )

                logger.info(
                    f"[{request_id}] Reading file bytes | "
                    f"filename={file.filename}"
                )

                image_bytes = await file.read()
                input_size = len(image_bytes)
                total_input_bytes += input_size

                logger.info(
                    f"[{request_id}] File bytes read | "
                    f"filename={file.filename} | "
                    f"size={format_bytes(input_size)}"
                )

                logger.info(
                    f"[{request_id}] Opening image with PIL | "
                    f"filename={file.filename}"
                )

                input_image = Image.open(BytesIO(image_bytes)).convert("RGBA")

                logger.info(
                    f"[{request_id}] Image opened successfully | "
                    f"filename={file.filename} | "
                    f"mode={input_image.mode} | "
                    f"width={input_image.width} | "
                    f"height={input_image.height}"
                )

                logger.info(
                    f"[{request_id}] Running background removal model | "
                    f"filename={file.filename}"
                )

                model_start_time = time.time()
                output_image = remove(input_image, session=session)
                model_duration_ms = (time.time() - model_start_time) * 1000

                logger.info(
                    f"[{request_id}] Background removal completed | "
                    f"filename={file.filename} | "
                    f"duration={model_duration_ms:.2f}ms"
                )

                logger.info(
                    f"[{request_id}] Saving processed image as PNG | "
                    f"filename={file.filename}"
                )

                image_output_buffer = BytesIO()
                output_image.save(image_output_buffer, format="PNG")
                image_output_buffer.seek(0)

                output_bytes = image_output_buffer.getvalue()
                output_size = len(output_bytes)
                total_output_bytes += output_size

                original_name = file.filename or f"image_{index}"
                name_without_extension = os.path.splitext(original_name)[0]
                output_filename = f"{name_without_extension}_background_removed.png"

                logger.info(
                    f"[{request_id}] Writing processed image to ZIP | "
                    f"original_filename={file.filename} | "
                    f"zip_filename={output_filename} | "
                    f"output_size={format_bytes(output_size)}"
                )

                zip_file.writestr(output_filename, output_bytes)

                processed_count += 1

                file_duration_ms = (time.time() - file_start_time) * 1000

                logger.info(
                    f"[{request_id}] File processed successfully | "
                    f"filename={file.filename} | "
                    f"duration={file_duration_ms:.2f}ms"
                )

        zip_buffer.seek(0)

        zip_size = len(zip_buffer.getvalue())
        total_duration_ms = (time.time() - start_time) * 1000

        logger.info(
            f"[{request_id}] ZIP file created successfully | "
            f"processed_count={processed_count} | "
            f"total_input_size={format_bytes(total_input_bytes)} | "
            f"total_output_png_size={format_bytes(total_output_bytes)} | "
            f"zip_size={format_bytes(zip_size)}"
        )

        logger.info(
            f"[{request_id}] Multiple image request successful | "
            f"total_duration={total_duration_ms:.2f}ms"
        )

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="background_removed_images.zip"'
            },
        )

    except HTTPException as e:
        total_duration_ms = (time.time() - start_time) * 1000

        logger.warning(
            f"[{request_id}] Multiple image request rejected | "
            f"status={e.status_code} | "
            f"detail={e.detail} | "
            f"duration={total_duration_ms:.2f}ms"
        )

        raise

    except Exception as e:
        total_duration_ms = (time.time() - start_time) * 1000

        logger.error(
            f"[{request_id}] Multiple image request failed | "
            f"processed_count={processed_count if 'processed_count' in locals() else 0} | "
            f"duration={total_duration_ms:.2f}ms | "
            f"error={str(e)}"
        )
        logger.error(traceback.format_exc())

        raise HTTPException(
            status_code=500,
            detail=f"Failed to remove backgrounds: {str(e)}"
        )