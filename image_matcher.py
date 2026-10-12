
from PIL import Image, ImageOps
from collections import Counter
import os


def get_image_features(image_path, size=(64, 64)):
    """Convert an image into a normalized, small RGB pixel representation."""
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image = ImageOps.fit(image, size)

        return list(image.getdata())


def compare_images(image_path_1, image_path_2):
    """Return a simple similarity score between two images (0 to 100)."""
    pixels_1 = get_image_features(image_path_1)
    pixels_2 = get_image_features(image_path_2)

    differences = [
        abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
        for (r1, g1, b1), (r2, g2, b2) in zip(pixels_1, pixels_2)
    ]

    maximum_difference = 255 * 3
    average_difference = sum(differences) / len(differences)

    score = 100 * (1 - average_difference / maximum_difference)
    return round(max(0, min(100, score)), 2)