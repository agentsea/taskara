import base64
import re
from io import BytesIO

from PIL import Image


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
