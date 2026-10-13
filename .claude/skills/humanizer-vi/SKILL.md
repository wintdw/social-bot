---
name: humanizer-vi
description: |
  Sửa văn bản tiếng Việt để bớt giọng AI: đọc lại một caption hoặc đoạn văn và
  bỏ các mẫu máy móc (mở bài công thức, cặp đối lập "không phải X mà là Y",
  câu chốt khuôn, bộ ba liệt kê theo quy tắc, nhịp câu đều, gạch đậm và tiêu đề
  ở mọi mục, cụm chuyển ý rỗng, hype rỗng), giữ nguyên ý và sự kiện. Dùng khi
  người dùng nói "nghe như AI", "viết lại tự nhiên hơn", "humanize", "bớt sáo",
  hoặc khi rà một caption trước khi lưu.
---

# Humanizer (tiếng Việt)

Mục tiêu: văn nghe như một người cụ thể viết cho một người đọc cụ thể. Không phải
làm văn tệ đi. Giữ nguyên ý, số liệu, tên riêng và mọi sự kiện. Không bịa thêm
chi tiết, không thêm lời kêu gọi tương tác.

## Vì sao văn AI nghe như AI

Mô hình chọn cách nói an toàn nhất cho mọi người đọc. Người viết thật chọn cho
một người đọc và một chủ đề, nên lựa chọn của họ không đều và rất cụ thể. Mỗi mẫu
dưới đây là một dạng của lựa chọn mặc định đó.

## Quy trình

1. **Đọc hết một lượt, chưa sửa.** Ghi lại đoạn nào nghe như máy.
2. **Gắn nhãn từng mẫu** theo bảng bên dưới. Một câu có thể có nhiều mẫu.
3. **Viết lại từng đoạn có nhãn.** Ưu tiên cụ thể hơn là đổi từ đồng nghĩa.
4. **Đọc lại cả bài** để kiểm tra: còn chỗ nào đều nhịp không, còn chỗ nào nói
   chung chung không, và ý có đổi không.
5. **Báo lại** danh sách đã sửa, và điểm nào cần người viết xác nhận (ví dụ một
   con số bị mất khi viết lại).

## Các mẫu cần nhận diện

### 1. Mở bài công thức
Mở bằng khuôn quen: "Ai cũng biết…", "Ai cũng nói…", "Chúng ta đều biết…", "Bạn có
biết…", "Hãy tưởng tượng…", "Trong thế giới…", "Có một sự thật…", "Sự thật là…".
**Sửa:** vào thẳng một khoảnh khắc, một con số, hoặc một câu hỏi thật về việc
đang nói.

### 2. Đối lập để nhấn mạnh
"không phải X, mà là Y", "không nằm ở X mà ở Y", "không chỉ… mà còn…" lặp nhiều
lần trong một bài. Một lần dùng là đắt, lặp là mẫu.
**Sửa:** giữ một cặp đối lập thật sự cần, còn lại nói thẳng Y.

### 3. Câu chốt khuôn
Câu cuối nhắc lại điều vừa nói bằng giọng sâu sắc: "Và đó chính là…", "Hãy nhớ
rằng…", "Cuối cùng, điều quan trọng là…". Câu chốt nhắc lại ý đã nói hoặc một
hình ảnh cũ là dấu hiệu của khuôn.
**Sửa:** kết ở ý cuối cùng thật, hoặc bỏ luôn câu chốt.

### 4. Bộ ba liệt kê theo quy tắc
"nhanh, gọn, chính xác", "rõ ràng, dễ hiểu, hữu ích". Ba vế cùng hình dạng, chỉ
để cho đủ bộ ba. Ngoại lệ là khi có đúng ba thứ thật.
**Sửa:** rút còn hai vế, hoặc giữ vế đắt nhất.

### 5. Nhịp câu đều
Mọi câu dài gần bằng nhau, cùng cấu trúc. Đọc lên như đọc máy.
**Sửa:** xen một câu ngắn, một câu dài, và một câu cụt khi ý đòi hỏi.

### 6. Gạch đậm và tiêu đề ở mọi mục
Caption mà có nhiều chữ in đậm, nhiều tiêu đề nhỏ, mỗi đoạn một nhãn.
**Sửa:** bỏ bớt định dạng, để một đoạn văn chạy liền mạch.

### 7. Cụm chuyển ý rỗng
"Về cơ bản", "Trong bối cảnh hiện nay", "Có thể nói rằng", "Không thể phủ nhận
rằng", "Một cách tổng quát". Đây là cụm đệm, không thêm nghĩa.
**Sửa:** cắt, rồi nói thẳng ý.

### 8. Phóng đại và hype rỗng
"cách mạng", "đột phá", "thay đổi mọi thứ", "số một", "vô song". Và các mô tả
phóng đại kiểu "quan trọng bậc nhất" khi không có số liệu đi kèm.
**Sửa:** thay bằng đúng điều đã xảy ra, với số nếu có.

### 9. Hedge rồi khẳng định
"Có lẽ đây là…, nhưng thực ra…" lặp lại ở nhiều câu. Rào đón không có lý do.
**Sửa:** khẳng định khi có căn cứ, nói rõ điều chưa chắc khi thật sự chưa chắc.

### 10. Dấu vết của chatbot
"Tuyệt vời!", "Dưới đây là…", "Hy vọng bài viết hữu ích", câu trả lời lặp lại
câu hỏi. Đây là phần còn sót lại của khung trò chuyện, không thuộc về bài đăng.
**Sửa:** xóa.

### 11. Giọng chung chung
Câu đúng với mọi chủ đề: "Công nghệ đang thay đổi cuộc sống", "Kỹ năng này rất
quan trọng". Đọc xong không biết ai nói, nói về cái gì.
**Sửa:** thay bằng một chi tiết thật của bài: việc gì, ai, lúc nào, kết quả ra
sao. Nếu không có chi tiết thật, hỏi người viết, đừng bịa.

## Những điều không được làm

- Không thêm sự kiện, số liệu, tên, trích dẫn mới.
- Không đổi nghĩa để cho "hay hơn".
- Không thêm lời kêu gọi tương tác ("tag bạn bè", "share để nhận quà") hay câu
  hỏi chỉ để kéo bình luận.
- Không bỏ dòng mở đầu mà người viết đã chọn (ví dụ nhãn `[Học cùng Atento]`).
- Không dịch thuật ngữ kỹ thuật đã giữ tiếng Anh (Elasticsearch, index, query…).
- Không đổi cách xưng hô đã chọn trong một bài. Đừng trộn "tôi" và "mình".

## Giữ giọng

Sửa để bớt máy, không để bài đồng dạng. Nếu người viết đã chọn một giọng (ví dụ
giọng kể chuyện, giọng kỹ thuật), giữ giọng đó và chỉ cắt những mẫu nêu trên.
