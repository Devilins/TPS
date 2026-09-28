"""
Нарезка одной ROI-ячейки на отдельные рукописные цифры и классификация каждой
через лёгкую CNN (обучена на MNIST, экспортирована в TFLite — ~33КБ, инференс
единицы мс на 1 ядре). Модель обучалась на "чужих" цифрах — точность на вашем
реальном почерке дообучится позже на данных из ревью (см. FieldResult.confirmed_value).
"""
import os
import threading

import cv2
import numpy as np

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "models_data", "digit_cnn.tflite")

_interpreter = None
_lock = threading.Lock()


def _get_interpreter():
    """Ленивая загрузка + переиспользование одного интерпретатора на процесс
    воркера — повторная загрузка модели на каждую задачу тратит время и RAM.
    На сервере ставьте лёгкий `tflite-runtime` (несколько МБ), а не полный
    tensorflow (сотни МБ) — здесь пробуем сначала его, для локальной разработки
    падаем обратно на tensorflow, если tflite-runtime не ставился."""
    global _interpreter
    if _interpreter is None:
        with _lock:
            if _interpreter is None:
                try:
                    from ai_edge_litert.interpreter import Interpreter  # актуальный лёгкий рантайм (бывший tflite-runtime)
                except ImportError:
                    try:
                        from tflite_runtime.interpreter import Interpreter  # старое имя пакета, на случай если ai-edge-litert не встал
                    except ImportError:
                        import tensorflow as tf  # только для разработки
                        Interpreter = tf.lite.Interpreter
                interp = Interpreter(model_path=_MODEL_PATH)
                interp.allocate_tensors()
                _interpreter = interp
    return _interpreter


def _mnist_style_center(digit_mask: np.ndarray):
    """Вписываем цифру в 20x20 с сохранением пропорций и центрируем в 28x28 по
    центру масс — так же готовился исходный MNIST."""
    ys, xs = np.where(digit_mask > 0)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    crop = digit_mask[y0:y1, x0:x1]
    h, w = crop.shape
    scale = 20.0 / max(h, w)
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((28, 28), dtype="float32")
    m = cv2.moments(resized.astype("uint8"))
    cx, cy = (m["m10"] / m["m00"], m["m01"] / m["m00"]) if m["m00"] > 0 else (new_w / 2, new_h / 2)
    off_x, off_y = int(round(14 - cx)), int(round(14 - cy))
    for yy in range(new_h):
        for xx in range(new_w):
            ty, tx = yy + off_y, xx + off_x
            if 0 <= ty < 28 and 0 <= tx < 28:
                canvas[ty, tx] = resized[yy, xx]
    return canvas


def segment_digits(cell_gray: np.ndarray) -> list[np.ndarray]:
    """Возвращает список 28x28 масок отдельных цифр слева направо."""
    _, binary = cv2.threshold(cell_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < 15 or h < cell_gray.shape[0] * 0.15:
            continue
        if w / h > 2.2:  # прочерк «–»: широкий и плоский, не цифра
            continue
        boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[0])

    digits = []
    for x, y, w, h in boxes:
        mask = binary[y:y + h, x:x + w].astype("float32") / 255.0
        centered = _mnist_style_center(mask)
        if centered is not None:
            digits.append(centered)
    return digits


def classify_digit(img28: np.ndarray) -> tuple[int, float]:
    interp = _get_interpreter()
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    x = img28.reshape(1, 28, 28, 1).astype("float32")
    interp.set_tensor(inp["index"], x)
    interp.invoke()
    probs = interp.get_tensor(out["index"])[0]
    return int(np.argmax(probs)), float(np.max(probs))


def ocr_cell(warped_img: np.ndarray, box: dict, pad: int = 6):
    """box — {"x0","y0","x1","y1"} из ROI-карты. Возвращает (текст, мин_confidence)."""
    x0, y0 = box["x0"] + pad, box["y0"] + pad
    x1, y1 = box["x1"] - pad, box["y1"] - pad
    crop = warped_img[y0:y1, x0:x1]
    if crop.size == 0:
        return "", None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    digits = segment_digits(gray)
    if not digits:
        return "", None
    results = [classify_digit(d) for d in digits]
    text = "".join(str(r[0]) for r in results)
    confidence = min(r[1] for r in results)
    return text, confidence
