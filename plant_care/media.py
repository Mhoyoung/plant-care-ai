"""업로드한 사진을 검증하고, 메타데이터를 제거해 저장한다."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_PIXELS = 25_000_000


def save_photo(data: bytes | None, data_root: Path) -> str | None:
    if data is None:
        return None
    if not data or len(data) > MAX_PHOTO_BYTES:
        raise ValueError("사진은 10MB 이하의 JPG, PNG, WEBP 파일로 올려주세요.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("JPG, PNG, WEBP 사진만 저장할 수 있어요.")
                if source.width * source.height > MAX_PHOTO_PIXELS:
                    raise ValueError("사진이 너무 커요. 2,500만 화소 이하로 줄여주세요.")
                source.verify()
            with Image.open(BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((1600, 1600))
                clean = Image.new("RGB", image.size, "white")
                clean.paste(image, mask=image.getchannel("A"))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("사진을 읽을 수 없어요. 다른 JPG, PNG, WEBP 파일을 선택해 주세요.") from error
    relative = Path("photos") / f"{uuid4().hex}.jpg"
    destination = data_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        clean.save(destination, format="JPEG", quality=88)
    except OSError:
        destination.unlink(missing_ok=True)
        raise
    return relative.as_posix()
