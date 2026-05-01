from PIL import Image

from actual_discord_bot.receipts.preprocessing import preprocess_image


class TestImagePreprocessing:
    def test_converts_to_grayscale(self):
        # Start with an RGB image
        image = Image.new("RGB", (100, 100), color=(128, 64, 200))
        result = preprocess_image(image)
        assert result.mode == "L"

    def test_output_is_binarized(self):
        """Output should only contain black (0) and white (255) values after binarization."""
        image = Image.new("L", (100, 100), color=128)
        result = preprocess_image(image)
        pixels = set(result.getdata())
        assert pixels.issubset({0, 255})

    def test_white_image_stays_white(self):
        image = Image.new("RGB", (50, 50), color=(255, 255, 255))
        result = preprocess_image(image)
        assert all(p == 255 for p in result.getdata())

    def test_black_image_stays_black(self):
        image = Image.new("RGB", (50, 50), color=(0, 0, 0))
        result = preprocess_image(image)
        assert all(p == 0 for p in result.getdata())

    def test_preserves_dimensions(self):
        image = Image.new("RGB", (200, 300))
        result = preprocess_image(image)
        assert result.size == (200, 300)
