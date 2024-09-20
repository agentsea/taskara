import base64
import re
from io import BytesIO
import mimetypes
import os
import secrets
import string
import tempfile
from typing import List

from google.cloud import storage
from PIL import Image

from .env import STORAGE_BUCKET_ENV, STORAGE_SA_JSON_ENV


def image_to_b64(img: Image.Image, image_format="PNG") -> str:
    """Converts a PIL Image to a base64-encoded string with MIME type included.

    Args:
        img (Image.Image): The PIL Image object to convert.
        image_format (str): The format to use when saving the image (e.g., 'PNG', 'JPEG').

    Returns:
        str: A base64-encoded string of the image with MIME type.
    """
    buffer = BytesIO()
    img.save(buffer, format=image_format)
    image_data = buffer.getvalue()
    buffer.close()

    mime_type = f"image/{image_format.lower()}"
    base64_encoded_data = base64.b64encode(image_data).decode("utf-8")
    return f"data:{mime_type};base64,{base64_encoded_data}"


def b64_to_image(base64_str: str) -> Image.Image:
    """Converts a base64 string to a PIL Image object.

    Args:
        base64_str (str): The base64 string, potentially with MIME type as part of a data URI.

    Returns:
        Image.Image: The converted PIL Image object.
    """
    # Strip the MIME type prefix if present
    if "," in base64_str:
        base64_str = base64_str.split(",")[1]

    image_data = base64.b64decode(base64_str)
    image = Image.open(BytesIO(image_data))
    return image


def parse_image_data(image_data_str: str):
    """Parses the image data URL to extract the MIME type and base64 data."""
    data_url_pattern = re.compile(
        r"data:(?P<mime_type>[^;]+);base64,(?P<base64_data>.+)"
    )
    match = data_url_pattern.match(image_data_str)
    if not match:
        raise ValueError("Invalid image data format")
    mime_type = match.group("mime_type")
    base64_data = match.group("base64_data")
    return mime_type, base64_data


def generate_random_suffix(length: int = 24) -> str:
    """Generates a random suffix for the image file name."""
    return "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(length)
    )


def upload_image_to_gcs(image_data: bytes, mime_type: str) -> str:
    """Uploads an image to Google Cloud Storage and returns the public URL."""
    sa_json = os.getenv(STORAGE_SA_JSON_ENV)
    if not sa_json:
        raise ValueError(f"Environment variable {STORAGE_SA_JSON_ENV} not set")

    # Check if the service account JSON is a path or a JSON string
    if sa_json.startswith("{"):
        # Assume it's a JSON string, write to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_file:
            temp_file.write(sa_json.encode())
            temp_file_name = temp_file.name
    else:
        # Assume it's a path to a JSON file
        temp_file_name = sa_json

    storage_client = storage.Client.from_service_account_json(temp_file_name)

    bucket_name = os.getenv(STORAGE_BUCKET_ENV)
    if not bucket_name:
        raise ValueError(f"Environment variable {STORAGE_BUCKET_ENV} not set")

    bucket = storage_client.bucket(bucket_name)

    random_suffix = generate_random_suffix()
    extension = mimetypes.guess_extension(mime_type)
    blob_name = f"images/{random_suffix}{extension}"
    blob = bucket.blob(blob_name)

    # Create a temporary file to write the image data
    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temp_file:
        temp_file.write(image_data)
        temp_file_name = temp_file.name

    # Upload the temporary file to Google Cloud Storage
    blob.upload_from_filename(temp_file_name)
    blob.content_type = mime_type
    blob.make_public()

    # Delete the temporary file
    os.remove(temp_file_name)

    return blob.public_url


def convert_images(images: List[str | Image.Image]) -> List[str]:
    sa = os.getenv(STORAGE_SA_JSON_ENV)
    new_imgs: List[str] = []
    if sa:
        for img in images:
            if isinstance(img, Image.Image):
                new_imgs.append(image_to_b64(img))
            elif isinstance(img, str):
                if img.startswith("data:"):
                    mime_type, base64_data = parse_image_data(img)
                    image_data = base64.b64decode(base64_data)
                    public_url = upload_image_to_gcs(image_data, mime_type)
                    new_imgs.append(public_url)
                elif img.startswith("https://"):
                    new_imgs.append(img)
                else:
                    loaded_img = Image.open(img)
                    b64_img = image_to_b64(loaded_img)
                    mime_type, base64_data = parse_image_data(b64_img)
                    image_data = base64.b64decode(base64_data)
                    public_url = upload_image_to_gcs(image_data, mime_type)
                    new_imgs.append(public_url)
            else:
                raise ValueError("unnknown image type")
    else:
        for img in images:
            if isinstance(img, Image.Image):
                new_imgs.append(image_to_b64(img))
            elif img.startswith("data:") or img.startswith("https://"):
                new_imgs.append(img)
            else:
                loaded_img = Image.open(img)
                b64_img = image_to_b64(loaded_img)
                new_imgs.append(b64_img)

    return new_imgs
