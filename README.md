# Pipeline dịch manga (mokuro → clean + typeset)

Quy trình hoàn chỉnh để biến một thư mục ảnh manga tiếng Nhật thành bản tiếng Việt
đã xóa chữ gốc và chèn bản dịch, xuất ra ảnh / PDF / CBZ.

## Cài đặt

```
pip install mokuro pillow opencv-python numpy anthropic deep-translator
```

> Dịch bằng Claude (mặc định) cần `anthropic` + biến môi trường `ANTHROPIC_API_KEY`.
> Nếu chỉ dùng Google/DeepL thì không cần `anthropic`.

## Các bước

```
┌────────┐  ┌────────┐  ┌────────┐  ┌─────────┐  ┌────────┐  ┌────────┐  ┌───────┐
│ .zip   │→ │0. unzip│→ │ 1. ocr │→ │2.extract│→ │3.transl│→ │4.render│→ │5.export│
│        │  │        │  │(mokuro)│  │+3b dịch │  │  +box  │  │(vẽ chữ)│  │PDF/CBZ │
└────────┘  └────────┘  └────────┘  └─────────┘  └────────┘  └────────┘  └───────┘
              folder/     .mokuro    .trans.json   điền "vi"   "… VI"/    .pdf .cbz
                          .html                                 ảnh           │
                                                                              ▼
                                                                       ┌────────────┐
                                                                       │  6. clean  │
                                                                       │ giữ mỗi PDF│
                                                                       └────────────┘
```

| Bước | Lệnh | Tạo ra |
|---|---|---|
| 0. Giải nén | `python manga_pipeline.py unzip "Chapter 14.zip"` | thư mục `Chapter 14/` |
| 1. OCR | `python manga_pipeline.py ocr "Chapter 14"` | `Chapter 14.mokuro`, `.html` |
| 2. Trích text | `python manga_pipeline.py extract "Chapter 14"` | `Chapter 14.trans.json` |
| 3. Dịch tự động | `python manga_pipeline.py translate "Chapter 14"` | điền các `"vi"` còn trống (mặc định engine Claude) |
| — Ráp box sót | `python manga_pipeline.py addbox "Chapter 14" --img 002.jpg --box X1 Y1 X2 Y2 --vi "..."` | thêm ô SFX |
| 4. Render | `python manga_pipeline.py render "Chapter 14" --clean inpaint` | thư mục `Chapter 14 VI/` |
| 5. Export | `python manga_pipeline.py export "Chapter 14"` | `Chapter 14 VI.pdf`, `.cbz` |
| 6. Dọn dẹp | `python manga_pipeline.py clean "Chapter 14" --yes` | xóa hết trung gian, **chỉ giữ PDF** |

## Bước dịch (`.trans.json`)

Mỗi ô text là một block. `translate` điền tự động các ô `"vi"` còn trống; ô có sẵn bản
dịch sẽ **không bị ghi đè** (an toàn để sửa tay rồi chạy lại). Ô `"vi"` để trống khi
render thì **giữ nguyên ảnh gốc**.

```json
{
  "box": [798, 959, 1017, 1085],   // toạ độ [x1,y1,x2,y2] dùng để xoá chữ gốc
  "vertical": false,
  "src": "mokuro",                 // "mokuro" hoặc "manual" (box thêm tay)
  "jp": "中世では浣腸は……",          // text gốc OCR (tham khảo)
  "vi": "Thời Trung Cổ, thụt tháo là đặc quyền của giới thượng lưu..."
}
```

- Chạy lại `extract` **giữ** cả bản dịch `"vi"` lẫn các box `"src": "manual"`.
- Sửa câu nào thì sửa trong `.trans.json` rồi chạy lại `render`.

## 3 tính năng nâng cao

### 1. Xoá thông minh bằng inpainting (`--clean inpaint`)
Mặc định. Thay vì tô khối trắng, chỉ xoá **nét chữ** rồi tái tạo nền bằng `cv2.inpaint`,
nên chữ nằm trên hình vẽ đỡ lộ vệt. Chữ tiếng Việt được vẽ kèm viền trắng mỏng cho nổi.
Dùng `--clean white` nếu muốn quay lại cách tô trắng cũ (nhanh hơn, không cần OpenCV).

### 2. Thêm box thủ công cho SFX mokuro bỏ sót (`addbox`)
Mokuro không nhận diện chữ vẽ tay / chữ nghệ thuật (không có toạ độ box). Thêm tay:

```
python manga_pipeline.py addbox "Chapter 14" --img 002.jpg --box 830 28 985 62 --vi "Rầmmm!!"
```

Cách lấy toạ độ: mở ảnh gốc bằng phần mềm xem ảnh (hoặc Paint) rồi đọc pixel `(x1,y1)`
góc trên-trái và `(x2,y2)` góc dưới-phải của vùng chữ. Box thêm tay được đánh dấu
`"src": "manual"` và không bị mất khi chạy lại `extract`.

### 3. Dịch tự động (`translate`)
- **Claude (mặc định — nhanh & chính xác nhất):** `--engine claude`
  - Dịch **cả chương trong 1 request** → nhanh hơn nhiều so với Google (gọi từng ô).
  - Hiểu ngữ cảnh, giọng điệu, SFX → chất lượng cao hơn dịch máy.
  - Cần `pip install anthropic` và biến môi trường `ANTHROPIC_API_KEY` (hoặc `--key`).
  - Chọn model: `--model claude-opus-4-8` (tốt nhất, mặc định), `claude-sonnet-4-6`
    (cân bằng), `claude-haiku-4-5` (rẻ/nhanh nhất).
- **Google (miễn phí, không cần key, nhưng chậm):** `--engine google`
- **DeepL (cần key):** `--engine deepl --key <API_KEY>`

```powershell
# đặt key 1 lần cho phiên PowerShell hiện tại
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python manga_pipeline.py translate "Chapter 15" --engine claude --model claude-sonnet-4-6
```

Chỉ dịch các ô `"vi"` còn trống và bỏ qua ô chỉ có dấu câu (．．．, ！！). Dịch máy nên
**luôn rà soát lại** `.trans.json` trước khi render.

## Tuỳ chỉnh (đầu file `manga_pipeline.py`)

| Biến | Ý nghĩa |
|---|---|
| `FONT_PATH` | Font chữ Việt (mặc định Arial Bold). Đổi sang font manga nếu muốn. |
| `PAD` | Số px nới rộng vùng xoá quanh chữ gốc. |
| `MAX_FONT` / `MIN_FONT` | Khoảng cỡ chữ tự động co giãn cho vừa khung. |
| `CLEAN_MODE` | Chế độ xoá mặc định: `"inpaint"` hoặc `"white"`. |
| `JPG_QUALITY` | Chất lượng JPG xuất ra. |

## Giải nén & dọn dẹp

### Giải nén (`unzip`)
Nếu chương tải về dạng `.zip`, giải nén thẳng thành thư mục ảnh:

```
python manga_pipeline.py unzip "Chapter 15.zip"          # -> thư mục "Chapter 15/"
python manga_pipeline.py unzip "Chapter 15.zip" --dest "Chapter 15"   # đổi tên đích
```

Tự động "kéo phẳng" nếu ảnh nằm trong một thư mục con lồng bên trong zip.

### Dọn dẹp (`clean`)
Sau khi có PDF cuối, xóa mọi file trung gian (`Chapter/`, `Chapter VI/`, `.mokuro`,
`.html`, `.trans.json`, `.cbz`, cache `_ocr/`), **chỉ giữ lại `Chapter VI.pdf`**:

```
python manga_pipeline.py clean "Chapter 15"            # XÓA LUÔN (mặc định)
python manga_pipeline.py clean "Chapter 15" --dry-run  # chỉ xem trước, không xóa
```

> ⚠️ `clean` mặc định **xóa thật ngay**, gồm cả **thư mục ảnh gốc** và `.trans.json`
> (không thể hoàn tác). Dùng `--dry-run` nếu chỉ muốn xem danh sách trước.
> Lệnh sẽ báo lỗi nếu chưa có `Chapter VI.pdf` (để không xóa nhầm khi chưa export).

## Chạy NHIỀU CHƯƠNG trong 1 lệnh (`batch`)

```powershell
$env:GEMINI_API_KEY = "AQ...key..."
python manga_pipeline.py batch 15 27 --engine gemini
```

`batch START END` chạy `auto` cho từng chương từ START đến END. Với mỗi số `N`, nó
tự tìm file `*Chapter N.zip` (hoặc thư mục `Chapter N` nếu đã giải nén). OCR tự động
trả lời "yes", chương nào lỗi sẽ bỏ qua và báo ở cuối (không làm dừng cả lô). Thêm
`--clean` để mỗi chương chỉ giữ lại PDF.

## Chạy 1 chương trong 1 lệnh (`auto`)

```powershell
python manga_pipeline.py auto "Chapter 15.zip"
```

Tự động chạy: `unzip → ocr → extract → translate (google) → render (inpaint) → export`.
Đầu vào có thể là **file `.zip`** hoặc **thư mục ảnh** có sẵn. Kết quả: `Chapter 15 VI.pdf`.

Tùy chọn:

| Cờ | Ý nghĩa |
|---|---|
| `--clean` | Xóa luôn file trung gian khi xong, **chỉ giữ PDF** |
| `--no-translate` | Bỏ qua dịch tự động (để tự điền `.trans.json` rồi `render` riêng) |
| `--engine deepl --key XXX` | Dùng DeepL thay Google |
| `--mode white` | Tô trắng thay vì inpaint |
| `--dest "Tên khác"` | Đổi tên thư mục đích khi giải nén zip |

Ví dụ làm trọn gói rồi dọn sạch, chỉ còn PDF:

```powershell
python manga_pipeline.py auto "Chapter 15.zip" --clean
```

> 💡 Muốn chất lượng dịch tốt hơn: chạy `auto --no-translate`, sửa tay `.trans.json`
> (và `addbox` cho SFX), rồi `render` + `export`.

## Hoặc chạy từng bước thủ công

```powershell
python manga_pipeline.py unzip     "Chapter 15.zip"
python manga_pipeline.py ocr       "Chapter 15"
python manga_pipeline.py extract   "Chapter 15"
python manga_pipeline.py translate "Chapter 15"   # mặc định Claude (cần ANTHROPIC_API_KEY)
#   → rà soát "Chapter 15.trans.json", sửa câu sai, addbox cho SFX nếu cần
python manga_pipeline.py render    "Chapter 15" --clean inpaint
python manga_pipeline.py export    "Chapter 15"
python manga_pipeline.py clean     "Chapter 15"
```
