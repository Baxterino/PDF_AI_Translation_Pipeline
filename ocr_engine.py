import pymupdf
import cv2
import numpy as np
import pytesseract
import os

FONT_PATH = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"

def process_vector_pdf_sync(input_pdf: str, output_pdf: str, progress_callback=None):
    if not os.path.exists(input_pdf):
        raise FileNotFoundError(f"Input file not found: {input_pdf}")

    doc = pymupdf.open(input_pdf)
    output_doc = pymupdf.open()
    total_pages = len(doc)

    for page_idx in range(total_pages):
        page = doc[page_idx]

        if progress_callback:
            progress_callback(page_idx + 1, total_pages)

        dpi = 200
        scale = 72.0 / dpi
        pix = page.get_pixmap(dpi=dpi)
        
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.h, pix.w, pix.n))
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)

        # 1. OCR text detection
        rgb_img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        data = pytesseract.image_to_data(rgb_img, lang="eng", output_type=pytesseract.Output.DICT)

        lines = {}
        for i in range(len(data["text"])):
            word = data["text"][i].strip()
            conf = int(data["conf"][i])

            if conf > 25 and word:
                block_num = data["block_num"][i]
                par_num = data["par_num"][i]
                line_num = data["line_num"][i]
                key = (block_num, par_num, line_num)

                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]

                if key not in lines:
                    lines[key] = {
                        "words": [word],
                        "x0": x, "y0": y,
                        "x1": x + w, "y1": y + h
                    }
                else:
                    lines[key]["words"].append(word)
                    lines[key]["x0"] = min(lines[key]["x0"], x)
                    lines[key]["y0"] = min(lines[key]["y0"], y)
                    lines[key]["x1"] = max(lines[key]["x1"], x + w)
                    lines[key]["y1"] = max(lines[key]["y1"], y + h)

        # 2. Inpaint text out of the background bitmap
        mask = np.zeros(img_bgr.shape[:2], dtype=np.uint8)
        for key, val in lines.items():
            cv2.rectangle(
                mask,
                (max(0, val["x0"] - 2), max(0, val["y0"] - 2)),
                (min(img_bgr.shape[1], val["x1"] + 2), min(img_bgr.shape[0], val["y1"] + 2)),
                255,
                -1
            )

        inpainted_bgr = cv2.inpaint(img_bgr, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

        # 3. Create fresh PDF page
        page_rect = page.rect
        new_page = output_doc.new_page(width=page_rect.width, height=page_rect.height)

        success, img_bytes = cv2.imencode(".png", inpainted_bgr)
        if success:
            new_page.insert_image(page_rect, stream=img_bytes.tobytes())

        # 4. Insert selectable vector text objects
        font_name = "custom_serif"
        if os.path.exists(FONT_PATH):
            new_page.insert_font(fontname=font_name, fontfile=FONT_PATH)
        else:
            font_name = "helv"

        for key, val in lines.items():
            text_line = " ".join(val["words"]).strip()
            if not text_line:
                continue

            pdf_x0 = val["x0"] * scale
            pdf_y0 = val["y0"] * scale
            pdf_x1 = max(val["x1"] * scale + 10, page_rect.width - 10)
            pdf_y1 = val["y1"] * scale + 4

            textbox_rect = pymupdf.Rect(pdf_x0, pdf_y0, pdf_x1, pdf_y1)
            target_fontsize = max(7.0, (val["y1"] - val["y0"]) * scale * 0.8)

            inserted = False
            for fs in np.arange(target_fontsize, 4.5, -0.5):
                res = new_page.insert_textbox(
                    textbox_rect,
                    text_line,
                    fontsize=float(fs),
                    fontname=font_name,
                    color=(0, 0, 0),
                    align=pymupdf.TEXT_ALIGN_LEFT
                )
                if res >= 0:
                    inserted = True
                    break

            if not inserted:
                new_page.insert_text(
                    pymupdf.Point(pdf_x0, val["y1"] * scale),
                    text_line,
                    fontsize=target_fontsize,
                    fontname=font_name,
                    color=(0, 0, 0)
                )

    output_doc.save(output_pdf, garbage=4, deflate=True)
    output_doc.close()
    doc.close()
