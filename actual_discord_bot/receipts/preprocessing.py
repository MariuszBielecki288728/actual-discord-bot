from PIL import Image, ImageFilter


def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Preprocess a receipt image for better OCR results.

    Steps:
    1. Convert to grayscale
    2. Apply sharpening filter
    3. Apply adaptive thresholding (binarization via point transform)
    """
    grayscale = image.convert("L")
    sharpened = grayscale.filter(ImageFilter.SHARPEN)
    threshold = 140
    binarized = sharpened.point(lambda x: 255 if x > threshold else 0, mode="1")
    return binarized.convert("L")
