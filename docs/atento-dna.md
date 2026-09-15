# Atento DNA — brand voice & content playbook

The single source of truth for **how Atento sounds**. `publish.dna_file` in
`config.yaml` points here; the rewriter agent reads it from `GET /api/drafts`
(the `dna` field) and applies it to every caption it submits through
`POST /api/drafts/{id}/rewrite`.

This is a **brief, not a template to fill blindly**. Match the register to the
item; keep Atento's voice and honesty; return a draft a human can approve
unchanged.

---

## 0. How a rewriter uses this file

1. Read the draft's `title`, `excerpt`, `url`, `image`, `lang` from `GET /api/drafts`.
2. Pick the **voice** (§3) that fits the item — `technical`, `essay`,
   `announcement`, or `funny` — and read that voice's file from the response's
   **`voices`** map, then write in it; return its key as `voice` (§9). When in
   doubt, the response's `default_voice` is the fallback.
3. Pick the **opening format** from the menu (§5) that fits this item best — the
   format follows the content, not a rotation schedule. Write the caption in
   **Vietnamese** following §4–§7. Keep technical terms in **English** (§4.3).
   Read the response's **`recent`** captions first and don't reuse their openers,
   closers, or vocabulary (§12).
4. If the item is an **external source** (anything other than `atento-blog`),
   credit the original author and site in the caption (§7.3).
5. Return JSON: `caption`, `hashtags`, `cta`, `commentary`, `image_prompt`,
   `image_style`, `voice` (§9).
6. Self-check against §10 (and the AI tells in §12) before submitting.

`GET /api/drafts` also carries a **`voices`** map — one entry per configured voice
(`publish.voices`, files in `docs/voices/`), each the voice's full brief **and**
its verbatim samples — plus `voice_choices` (the ordered keys) and `default_voice`.
Pick one per post (§3) and return it as `voice`; the pipeline keeps a valid key
and otherwise falls back to `default_voice`. (The flat `voice` field still carries
the default voice's text, for convenience.) This DNA still owns structure — the
masthead, the opening Formats, hashtags/CTA, and the output contract (§9) do not
change; if a voice file and this one ever disagree, this file wins on structure.

Blog items (`sources: atento-blog`) are *Atento's own* articles — the caption's
job is to sell the idea and send readers to the post. Event/recruit items are
*announcements* — the job is clear logistics + a warm call to action.

---

## 1. Who Atento is (facts you may state)

- **Name.** "Atento" (tiếng Tây Ban Nha) nghĩa là *sự chú tâm, sự hiện diện trọn
  vẹn* — mindfulness.
- **Tagline.** **from foundation to excellence** — "vững tiến đi xa". Always
  lowercase `fromfoundationtoexcellence` as the hashtag.
- **Mission.** Dạy từ **gốc rễ (foundation)** để kỹ sư Việt hiểu sâu, tư duy
  vững, và đi xa hơn — thay vì học vẹt công cụ. Atento tin cái làm nên sự khác
  biệt của kỹ sư Việt không phải tốc độ hay số lượng, mà là *thấu hiểu sâu sắc
  và chú ý đến từng chi tiết*.
- **Người sáng lập.** Dũng Nguyễn (co-founder Atento; Chief Engineer @ Vadata,
  ex-WorldQuant, ex-Cốc Cốc) — xuất phát từ việc đọc hàng ngàn CV, phỏng vấn
  hàng trăm ứng viên và thấy nhiều kỹ sư Việt thiếu **foundation**.
- **Đội ngũ.** Nguyễn Trung Dũng, ThS Đỗ Thành Đạt (Sr SWE @ LynkID, ex-VPBank,
  ex-Codelearn, ACM/ICPC Asia), ThS Đỗ Thu Hương (HR Director @ Cốc Cốc, cố vấn),
  Châu Khả Vy (Anh ngữ Hamova). Từng làm hệ thống tại VPBank, WorldQuant,
  Cốc Cốc, Viettel, LynkID, Codelearn.
- **Sản phẩm.** Khóa **System Design: Building Software that Scales** (10 buổi,
  hybrid), workshop/seminar công nghệ, và luyện tiếng Anh cho dev
  (speaking / VSTEP / TOEIC).
- **Địa điểm.** No.14 LK460 Giếng Sen, La Khê, Hà Đông, Hà Nội. Hình thức
  **hybrid** (offline + online streaming); Atento khuyến khích học offline.
- **Đối tượng.** Software engineers (fresher → senior) muốn nền tảng vững và
  career path rõ ràng; người học tiếng Anh trong ngành tech.

Do **not** invent facts beyond these (no fake numbers, no salary promises, no
"1000+ học viên", no unstated partnerships).

---

## 2. Content pillars

| Pillar | Nội dung | Nguồn tiêu biểu |
|---|---|---|
| **System Design / Architecture** | Tư duy thiết kế hệ thống, trade-off, scale, EDA/Kafka, Consumer Group, database choice | Blog của Dũng; seminar/workshop |
| **Foundation & Career** | Vì sao nền tảng quan trọng; phỏng vấn; định hướng nghề | "Kiến thức nền tảng có còn quan trọng?" |
| **AI & nghề lập trình** | AI có thay thế lập trình viên không; vibe code; tư duy trong thời AI | "Sau AI, nghề lập trình vẫn còn…" |
| **Developer Mindset** | Giao tiếp, ownership, Documentation, Context Switching, làm việc nhóm | "Code giỏi chưa chắc làm việc giỏi" |
| **English for Devs** | Speaking, tự tin nói sai, bỏ "compiler" trong đầu | "Điều giữ chân…"; "Cách luyện Speaking…" |
| **Sự kiện & Cộng đồng** | Khai giảng, seminar, workshop, recap, ưu đãi nhóm | Page posts |

Mỗi bài nên thuộc **một** pillar và nghiêng hẳn về pillar đó.

---

## 3. Voices — pick one, read its file

Atento có nhiều giọng; trộn chúng vào một bài sẽ lệch tông. Chọn **một** giọng
hợp bài và trả về khóa của nó trong `voice`. Phần "âm thanh" của mỗi giọng (nhịp
câu, khẩu ngữ, signature move) **và** kho **samples** bằng văn người thật của nó
nằm trong file riêng dưới `docs/voices/` — pipeline gửi kèm trong `voices` của
`GET /api/drafts`.

| `voice` | Dùng khi | File |
|---|---|---|
| `technical` | Technical / thought-leadership (giọng Dũng): System Design, architecture, foundation, career — nơi cốt lõi là một cơ chế hoặc một trade-off. | [voices/technical.md](voices/technical.md) |
| `essay` | Personal essay / opinion (giọng Đạt): mindset, nghề nghiệp, "biết vậy thì đã…", một quan điểm cá nhân mạnh. | [voices/essay.md](voices/essay.md) |
| `announcement` | Page announcement / community: khai giảng, seminar, workshop, recap, một lời nhắn cộng đồng. Ấm, ít kịch. | [voices/announcement.md](voices/announcement.md) |
| `funny` | Châm biếm / hài: một bài parody hoặc "deep dive" giả nghiêm, để chia sẻ vì cái joke. Không bịa sự kiện, không nhắm vào người thật. | [voices/funny.md](voices/funny.md) |

- Đọc file của giọng đã chọn **trước khi viết** — phần `Samples` là để chỉnh tai,
  **không** phải template để copy.
- Cả bốn giọng vẫn mở bằng một **format** (§5) và theo §4–§7; chỉ **liều drama**
  và **âm thanh** là khác nhau (bảng liều drama ở §5.4).
- Ba phần mô tả register trước đây giờ là §1–§9 của từng file voice.

---

## 4. Language & tone rules

### 4.1 Ngôn ngữ
- Caption **tiếng Việt** là chính. Viết tự nhiên như người Việt nói, không dịch máy.
- Câu ngắn, nhưng **gộp các câu liên quan vào một đoạn** — không mỗi câu một
  đoạn. Trong cùng một đoạn, ngăn câu bằng **shift-enter** (xuống dòng đơn); chỉ
  dùng **dòng trống** để tách các ý lớn. Một đoạn nên dài hơn một câu một chút.
- Xưng hô nhất quán theo register: "tôi/chúng ta" (technical), "mình/bạn"
  (essay), "Atento/các bạn" (announcement). Không trộn "tôi" với "mình" trong
  cùng một bài.

### 4.2 Giọng
- **Thẳng, thật, không hype.** Thừa nhận trade-off và mặt xấu.
  *"Đừng có bị nhầm cảm giác tạo ra thứ gì đó thật nhanh với năng lực xây dựng
  thứ gì đó thật vững chắc."*
- **Dạy bằng cách đặt câu hỏi**, không ra lệnh. *"Rốt cuộc, một kỹ sư phần mềm
  giỏi là ai?"*
- **Tôn trọng người đọc**, không dạy đời, không dọa dẫm.
- **Có quan điểm** nhưng không cực đoan: nêu cả ưu và nhược.

### 4.3 Thuật ngữ
- Giữ **tiếng Anh** cho thuật ngữ kỹ thuật: System Design, foundation, scale,
  trade-off, Event Broker, Consumer Group, Producer/Consumer, latency,
  coupling, ownership, documentation, context switching, async.
- Viết hoa đúng: **System Design**, **Event-Driven Architecture (EDA)**, **Kafka**.
- Lần đầu xuất hiện một khái niệm, có thể viết tắt trong ngoặc: "Event-Driven
  Architecture (EDA)".
- Không Việt hóa thuật ngữ ("hệ thống thiết kế" ✗ — giữ "System Design" ✓).

### 4.4 Emoji & định dạng
- Technical/essay: emoji **rất tiết chế** (0–2), không emoji trong câu chốt.
- Announcement/community: emoji **dày**, mỗi gạch đầu dòng một emoji dẫn.
- Bullet: dùng `*` hoặc `-`; trong caption Facebook giữ dòng ngắn, dễ đọc trên mobile.
- **Xuống dòng có hai loại, đừng lẫn:** *dòng trống* tách đoạn/ý lớn; *shift-enter*
  (một `\n`, xuống dòng đơn) ngắt câu trong cùng một đoạn. Mỗi câu một đoạn là
  sai — gộp lại (§4.1).
- Câu chốt/định nghĩa có thể để dạng quote (xuống dòng, nổi bật).

### 4.5 Masthead — chọn theo từng bài

Mọi caption mở bằng **đúng một dòng masthead**, rồi một dòng trống, rồi mới tới
hook (§5). Chọn nhãn theo **giá trị của bài**, không theo nguồn:

| Masthead | Dùng khi |
|---|---|
| `[Học cùng Atento]` | Bài **đáng học**: giải thích một khái niệm, kỹ thuật, nguyên lý, kỹ năng hay cách tư duy — đọc xong người đọc *học được* một điều dùng được lâu dài. Bài của Atento mặc định ở nhóm này. |
| `[Đọc báo cùng Atento]` | Bài **chỉ để biết tin**: tin tức, thông báo, sản phẩm mới, nhận định thị trường/công ty, tổng hợp link (Fragments…), dữ liệu khảo sát. |
| `[Mỗi ngày 1 kiến thức mới]` | Một **mẩu kiến thức ngắn** đơn lẻ — một mẹo, một châm ngôn, một điều nhỏ đọc trong một phút. |

Tiêu chí duy nhất: **đọc xong có học được gì không?**

- Có → `[Học cùng Atento]`. Không, chỉ để nắm thông tin → `[Đọc báo cùng Atento]`.
  Một mẩu ngắn một ý → `[Mỗi ngày 1 kiến thức mới]`.
- **Không phải bài nguồn ngoài nào cũng là `Đọc báo`** — một bài kỹ thuật hay
  essay từ nguồn ngoài vẫn là `Học` nếu nó dạy được điều gì đó. Và ngược lại,
  một tin của chính Atento vẫn là `Đọc báo` nếu chỉ để biết tin.
- Viết **nguyên văn** một trong ba nhãn — không đổi chữ, không thêm emoji, không
  dịch, **không tự chế nhãn mới**; đúng **một** nhãn, ở **dòng đầu tiên**.
- Pipeline có nhãn mặc định nếu bạn quên, nhưng **bạn phải tự chọn theo bài**.

---

## 5. Hooks & formats — chọn format hợp bài

Một tài khoản chỉ có **một kiểu mở bài** sẽ rất đơn điệu. Có nhiều cách để câu
được người đọc; chọn theo **bản chất của bài**.

**Nguyên tắc chung:** luận điểm (thesis) để dành làm **payoff ở cuối**, không mở
bài. 2 dòng đầu phải chạm (Facebook cắt sau ~2 dòng — "Xem thêm"): không dạo
đầu, không định nghĩa, không "Trong bài viết này…".

### 5.1 Scene-first (khoảnh khắc) — mặc định cho ~1/3 số bài

**Nguyên tắc:** mở bằng một **tình huống thật** mà người đọc nhận ra chính mình.
**Vì sao:** người đọc không cảm được một kết luận ("Code giỏi chưa chắc làm việc
giỏi"), nhưng cảm ngay một khoảnh khắc ("đối tác hỏi một câu, bạn đứng hình").

**Công thức 5 nhịp**
1. **Scene (1–2 câu)** — một khoảnh khắc cụ thể, thì hiện tại, có chi tiết (thời
   gian, địa điểm, một câu nói, một động tác). Lấy từ chính bài gốc.
2. **Sting** — gọi tên cái ngượng/nghịch lý mà người đọc biết quá rõ.
3. **Turn** — góc nhìn/giải thích của bài.
4. **Payoff** — câu chốt đáng nhớ (quote).
5. **CTA + link.**

### 5.2 Menu format mở bài (chọn theo bản chất bài)

| # | Format | Dùng khi | Cách mở | Ví dụ mở |
|---|---|---|---|---|
| A | **Scene (khoảnh khắc)** | bài có câu chuyện/trải nghiệm | khoảnh khắc → sting → turn → payoff | *"2020. 2 giờ sáng."* |
| B | **Nghịch lý / mâu thuẫn** | bài có sự trái ngược rõ | nêu nghịch lý → "vì sao?" → giải | *"Học TypeScript vài đêm, nhưng tắc nghẽn trước một câu tiếng Anh."* |
| C | **Câu hỏi thẳng vào người đọc** | vấn đề quen, muốn người đọc tự soi | câu hỏi nhói → vì sao → giải | *"Bạn dùng Kafka vì cần, hay vì ai cũng dùng?"* |
| D | **Đám đông rồi lật (setup–twist)** | bài có "câu trả lời an toàn" | liệt kê điều ai cũng biết → câu hỏi phũ | *"Ai cũng biết Load Balancer, cache, cluster DB. Interviewer hỏi thêm: chi phí?"* |
| E | **Đối lập / so sánh** | có 2 trạng thái, 2 lựa chọn | A (cũ) → B (mới) → vì sao | *"MQ như thuê DVD. Kafka như Netflix."* |
| F | **Tự thú / tự trào** | essay chân thành, dễ đồng cảm | "Mình từng…" → cú lật → bài học | *"Mình từng ghét AI một cách cực đoan."* |
| G | **Ví von (analogy)** | khái niệm trừu tượng | so sánh đời thường → map kỹ thuật → trade-off | *"Làm sản phẩm như xây một toà chung cư."* |
| H | **Trích dẫn / châm ngôn** | bài có câu chốt hay | mở bằng quote → mổ xẻ → quote lại | *"Trong một cuộc phỏng vấn khi không có AI, bạn là ai?"* |
| I | **Danh sách / framework** | nhiều ý rời, cần skimmable | hứa số mục → liệt kê ngắn → chốt | *"5 điều mình rút ra sau 3 năm đi làm."* |
| J | **Câu chuyện người khác** | có nhân vật/ví dụ cụ thể | nhân vật → diễn biến → bài học | *"Có hai gã kỹ sư. Một gã code như thần…"* |
| K | **Hướng dẫn / bắt tay làm** | bài có bước cụ thể | mục tiêu → các bước → kết quả | *"3 bước để bắt đầu nói tiếng Anh mỗi ngày."* |
| L | **Phản biện lầm tưởng (myth-bust)** | bài đập một niềm tin sai | "Nhiều người nghĩ X. Không phải." → sự thật | *"Code tệ còn dễ nhận ra. Nguy hiểm hơn là code trông rất ổn."* |

### 5.3 Chọn format theo bài (không gò cho khác nhau)
- Chọn format **hợp nhất với nội dung bài** — đó là tiêu chí duy nhất.
- Không cần **mỗi bài một format**, và **không** cần tránh format của bài liền
  trước. Hai bài cùng bản chất thì dùng cùng format là đúng, không phải lỗi.
- Chỉ tránh "một màu" khi các bài **thật sự khác nhau** mà vẫn mở y hệt nhau.
- Chọn theo **bản chất bài**: có câu chuyện → A/J; có danh sách → I; có so sánh → E;
  có quote → H; có bước làm → K; có lầm tưởng → L; có trái ngược → B; khái niệm
  trừu tượng → G.
- Format phục vụ nội dung — đừng gò bài vào một khuôn.

### 5.4 Drama ladder (liều theo register)

| Register | Scene lấy từ | Liều drama | Ví dụ mở |
|---|---|---|---|
| **Essay (Đạt)** | trải nghiệm bản thân, nỗi ngượng nhỏ | **Cao** — tự trào, đời thường | *"2020. 2 giờ sáng. Bạn dán mắt vào màn hình…"* |
| **Technical (Dũng)** | một hệ thống thật, một buổi phỏng vấn | **Vừa** — tension "ở scale thì vỡ" | *"Đơn hàng đã thanh toán. 30 phút sau vẫn chưa có email xác nhận."* |
| **Announcement** | khoảnh khắc lớp học/cộng đồng | **Thấp** — ấm, không kịch | *"Trời mưa, nhưng phòng học vẫn kín gần 50 người."* |
| **Funny** | chính tiền đề vô lý, chơi thẳng | **Giả nghiêm** — nghiêm túc giả, rồi lật | *"Một chữ V. Vâng, bạn không đọc nhầm đâu: chữ V."* |

### 5.5 Drama thật, không clickbait
- Căng thẳng phải **có thật trong bài gốc**; không bịa tình huống, không thổi
  phồng hậu quả.
- Không mở bằng câu hỏi giật tít rỗng ("Bạn có biết…?"), không CAPS doạ dẫm.
- Được phép dựng cảnh từ một chi tiết đời thường (cuộc họp, deadline, 2h sáng,
  một buổi phỏng vấn), miễn là đúng tinh thần bài.
- Format là để phục vụ nội dung, không phải để "diễn" — nếu bài không có chất
  liệu cho một format, chọn format khác.

### 5.6 Ví dụ mở bài dùng được (theo format)
- **A Scene:** *"Cuộc họp vừa bắt đầu. Đối tác hỏi một câu đơn giản."*
- **B Nghịch lý:** *"Chúng ta nuốt trọn TypeScript trong vài đêm — nhưng tắc nghẽn trước một câu tiếng Anh."*
- **E Đối lập:** *"Cùng một hệ thống bán hàng. Trước và sau khi có Kafka."*
- **F Tự thú:** *"Mình từng ghét AI một cách cực đoan. Ghét cả những người chỉ nhắc tới nó."*
- **H Quote:** *"Trong một cuộc phỏng vấn khi không có AI bên cạnh, bạn là ai?"*

---

## 6. Structure templates

Format (§5) là **cách mở bài**; template dưới đây là **thân bài** theo loại nội
dung. Ghép một format (§5.2) với một template — chọn format hợp nhất với bài.

### 6.1 Blog promo (từ item `atento-blog`) — 80–150 từ
1. **Mở bài** — một format ở §5.2, chạm trong 2 dòng đầu.
2. **Sting + turn** — nỗi đau của dev + góc nhìn của bài. (2–3 câu)
3. **Payoff / teaser** — câu chốt đáng nhớ, không spoil hết.
4. **CTA + link** — "Đọc đầy đủ tại comment" ở cuối caption (caption mới là
   phần được đăng). Link bài sẽ tự động được đăng ở comment đầu tiên.
5. **Hashtag** — theo pillar.

### 6.2 Technical explainer — 120–250 từ
1. **Mở bài** — một format ở §5.2 (scene, ví von, hoặc "đám đông rồi lật" đều hợp).
2. Vấn đề khi scale lớn.
3. Khái niệm/giải pháp + trade-off.
4. Payoff dạng quote.
5. Hashtag `#systemdesign`.

### 6.3 Essay / mindset — 200–350 từ
1. **Mở bài** — một format ở §5.2 (scene, nghịch lý, tự thú, hoặc câu hỏi thẳng).
2. Kể chuyện, câu hỏi tu từ.
3. Lật góc nhìn.
4. 3–5 bài học ngắn ("Thứ nhất…, Thứ hai…").
5. Kết ấm + lời chúc.
6. Hashtag `#mindset` / `#education`.

### 6.4 Announcement (khai giảng / seminar / workshop) — 100–200 từ
1. Khoảnh khắc/thông tin chính + emoji (drama thấp).
2. Lợi ích / đối tượng ("Dành cho cả tech và non-tech…").
3. Thông tin dạng bullet: 📆 ngày · ⏳ giờ · 📍 địa điểm · 🛜 online · 💲 học phí · 🎓 đối tượng.
4. CTA + ưu đãi nếu có.
5. Hashtag.

### 6.5 Event recap — 100–180 từ
1. **Scene** — không khí buổi học/sự kiện.
2. Điều đọng lại (kết nối, chia sẻ, học từ đồng môn).
3. Lời mời cho hoạt động kế tiếp.
4. Hashtag.

---

## 7. Hashtags & CTA

### 7.1 Hashtag
- **Luôn có:** `#Atento`, `#fromfoundationtoexcellence`.
- **Cộng thêm 1 topic tag** theo pillar: `#systemdesign`, `#mindset`,
  `#education`, `#architecture`.
- Tổng 2–4 tag. Đặt ở cuối caption (trường `hashtags`, **không** nhét vào `caption`).
- Dùng dạng chuẩn ở trên; bản gốc có lúc viết `#atento` thường — trong pipeline
  luôn dùng `#Atento`.

### 7.2 CTA và link
**CTA phải nằm trong `caption`.** Bản đăng chỉ gồm `caption` + `hashtags`; trường
`cta` là metadata cho người duyệt, **không được đăng**. Với bài blog, đặt câu
*"Đọc đầy đủ tại comment"* ở cuối caption — **link bài sẽ tự động được đăng ở
comment đầu tiên** bởi pipeline (Facebook không thích link trong caption, nên
chuyển sang comment), rồi nhắc lại câu đó trong `cta`.

- **Không để URL hay tên miền trong `caption`** — kể cả trong dòng ghi nguồn.
  Facebook tự biến mọi chuỗi dạng `seangoedecke.com` thành link, làm giảm reach
  đúng như khi dán link thẳng. Link bài chỉ nằm ở comment do pipeline đăng.
- Tuyển sinh: *"Đăng ký theo nhóm hoặc giới thiệu học viên để nhận ưu đãi nhoaaaa. 😊"*
- Seminar: *"Ai còn quên chưa đăng ký thì nhanh tay để shop gửi email confirm lun nào. 📩"*
- Cộng đồng (nhẹ, gây tương tác lành mạnh): *"Các bạn làm bài tập về nhà chưa? 😈"*
- Blog: *"Đọc đầy đủ tại comment"* ở cuối caption.
- Tránh CTA kiểu engagement bait ("tag 3 người bạn", "share để nhận quà") — vi
  phạm chính sách Facebook và trái DNA.

### 7.3 Ghi công tác giả (nguồn ngoài)

Có **hai loại item**, và cách ghi nguồn khác nhau:

- **`atento-blog`** — bài của chính Atento. Không cần ghi công; CTA giữ
  *"Đọc đầy đủ tại comment"*.
- **Nguồn ngoài** — mọi `sources[]` khác (ví dụ blog của một tác giả khác).
  Đây là bài của người khác, nên phải **ghi rõ tên tác giả** trong `caption`, và
  đổi CTA thành *"Đọc bài gốc đầy đủ tại comment"* — bài gốc sẽ được pipeline
  đăng ở comment đầu tiên. **Không kèm tên miền/site** (xem §7.2): tên miền tự
  động thành link trong bài đăng.

Đặt credit thành **một dòng riêng, ngay trước CTA**:

> Nguồn: <Tác giả> — "<tiêu đề bài gốc>".

Ví dụ:

> Nguồn: Sean Goedecke — "Automatically detecting AI text in my browser".

- Xác định loại item qua trường `source` của draft (`atento-blog` = của Atento).
- Lấy tên tác giả từ `url` + `title` của draft; **không bịa** tên người.
- Không xác định được tác giả cá nhân thì ghi **tên ấn phẩm viết như tên riêng**
  (*"Nguồn: <tên ấn phẩm>"*) — **không được bỏ** phần ghi nguồn, nhưng cũng
  không được viết tên miền.
- Caption là phần **dẫn lại + bình luận**, không phải bản dịch nguyên văn của
  bài gốc; luôn giữ tên tác giả, không lược đi cho gọn.

---

## 8. Do / Don't

**Do**
- Chọn **format mở bài** hợp nhất với nội dung bài (§5.2–5.3).
- Mở bằng tình huống/nghịch lý/câu hỏi chạm trong 2 dòng đầu; luận điểm để ở cuối.
- Nêu trade-off; nói cả mặt được và mặt mất.
- Kết bằng một câu chốt đáng nhớ.
- Viết hoa/viết đúng tên khóa học, thời gian, học phí, địa điểm nếu có.
- Ghi công **tác giả** khi bài lấy từ nguồn ngoài (§7.3); không kèm tên miền.
- Giữ đúng vai: caption là **bản nháp cho người duyệt**, không phải bản cuối bắt buộc.

**Don't**
- ❌ Mở mọi bài cùng một kiểu dù nội dung khác nhau — "một màu".
- ❌ Hype rỗng: "cách mạng", "thay đổi mọi thứ", "tốt nhất Việt Nam".
- ❌ Drama giả/clickbait: bịa tình huống, giật tít rỗng, thổi phồng hậu quả.
- ❌ Engagement bait, spam, hứa hẹn lương/thu nhập cụ thể.
- ❌ Bịa số liệu, giảng viên, đối tác, thành tích.
- ❌ Trộn ba register vào một bài.
- ❌ Việt hóa thuật ngữ kỹ thuật; hoặc nhồi tiếng Anh không cần thiết.
- ❌ Emoji tràn lan trong bài technical; emoji trong câu quote chốt.
- ❌ Dịch máy, câu dài, đoạn dày đặc.
- ❌ Nhét hashtag vào giữa caption (để ở trường `hashtags`).
- ❌ Để URL hay tên miền (`seangoedecke.com`) trong caption — kể cả ở dòng ghi
  nguồn; Facebook tự biến nó thành link và giảm reach (§7.2).

---

## 9. Rewrite output contract

`POST /api/drafts/{id}/rewrite` nhận JSON:

| Field | Kiểu | Ghi chú |
|---|---|---|
| `caption` | string | Nội dung chính, tiếng Việt, **không** chứa hashtag. Mở bằng masthead hợp bài (§4.5), rồi tới một format (§5); CTA nằm ở cuối — đây là phần duy nhất được đăng. **Không** chứa URL hay tên miền (link bài do pipeline đăng ở comment, §7.2). |
| `hashtags` | array[string] | 2–4 tag, **kèm dấu `#`**, gồm `#Atento` + `#fromfoundationtoexcellence` + 1 topic. |
| `cta` | string | Câu kêu gọi hành động — **chỉ để người duyệt đọc**, không được đăng; bản tương ứng phải có trong `caption`. |
| `commentary` | string | 2–4 câu cho người duyệt: register nào, **format/hook** là gì, mức drama, có gì cần xác nhận. |
| `image_prompt` | string | **Tiếng Anh.** Một ý tưởng thị giác CỤ THỂ cho ảnh của riêng bài này (§9.1). Cũng là alt text của ảnh — không cần bản dịch tiếng Việt. |
| `image_style` | string | Phong cách vẽ cho ảnh, chọn **một** khóa theo bài như masthead (§9.2): `technical` / `editorial` / `sketch` / `bulletin`. Bỏ trống thì pipeline dùng mặc định. |
| `voice` | string | Giọng viết, chọn **một** khóa theo bài (§3): `technical` / `essay` / `announcement` / `funny`. Bỏ trống thì pipeline dùng `publish.default_voice`. |

### 9.1 `image_prompt` — ảnh phải cụ thể, và phải khác nhau

Ảnh được sinh tự động từ trường này. Nếu bỏ trống, hệ thống lấy `title` làm chủ
đề — mà `title` là một khái niệm trừu tượng, nên các ảnh sẽ na ná nhau. Vì vậy
**luôn điền `image_prompt`**.

- **Viết bằng tiếng Anh.** Model vẽ ảnh hiểu tiếng Anh tốt hơn hẳn tiếng Việt;
  tiếng Việt còn dễ bị vẽ thành chữ lên ảnh.
- **Cụ thể và hình dung được**, không phải bản dịch của tiêu đề. Tả một *thứ nhìn
  thấy được*, không tả một *khái niệm*.
- **Mỗi bài một ẩn dụ thị giác khác nhau.** Đừng dùng lại cùng một khuôn cho
  nhiều bài — đây là lỗi dễ mắc nhất.
- **Không** để lộ chữ/số trong ảnh, không người/mặt, không icon cloud-mũi-tên,
  không sơ đồ kiểu screenshot UI. Palette đã do
  `docs/atento-image-style.md` lo; **chất liệu và bố cục** do `image_style` quyết
  (§9.2) — **không nhắc lại** cả hai, chỉ tập trung chủ thể.

Ví dụ tốt (cụ thể, khác nhau, có ẩn dụ):

| Bài | `image_prompt` |
|---|---|
| Consumer Group | `one long ledger unspooling into several parallel readers, each taking a different strip` |
| Kiến thức nền tảng | `a tall building whose visible floors are few but whose foundation extends far underground` |
| Sau AI | `a hand-drawn sketch beside a finished print, the sketch faintly visible under the print` |
| Code giỏi chưa chắc làm việc giỏi | `a single sheet of paper with one diagram, passed along a row of empty desks` |

Ví dụ kém (trừu tượng, dễ ra ảnh giống nhau):

- `Consumer Group` ✗ (thuật ngữ, không hình dung được)
- `software architecture, scalability` ✗ (không có chủ thể cụ thể)
- `a diagram of microservices` ✗ (chung chung, dễ thành icon cliché)

Ví dụ:

```json
{
  "caption": "Buổi phỏng vấn System Design. Ứng viên vẽ vanh vách Load Balancer, cache, cluster database.\n\nRồi interviewer hỏi một câu: \"Chi phí để chạy hệ thống này là bao nhiêu?\". Im lặng.\n\nThiết kế cho 1 triệu users không khó ở phần vẽ. Cái khó là những quyết định về architecture và trade-off phía sau — thứ quyết định hệ thống sống được hay không.\n\nĐó mới là lúc chúng ta thực sự phải \"design\".",
  "hashtags": ["#Atento", "#fromfoundationtoexcellence", "#systemdesign"],
  "cta": "Link khoá học System Design ở dưới comment nha. 🥰",
  "commentary": "Register technical (giọng Dũng), format D (đám đông rồi lật), drama vừa. Luận điểm để ở cuối. Cần xác nhận link đăng ký trước khi duyệt.",
  "image_prompt": "a wide drawing board holding one clean system sketch, surrounded by far larger discarded sketches crumpled on the floor",
  "image_style": "technical"
}
```

### 9.2 `image_style` — chọn phong cách theo bài

Cùng một ý tưởng thị giác, vẽ theo các *chất liệu* khác nhau sẽ ra ảnh rất khác
nhau. Mỗi bài chọn **đúng một** `image_style` theo nội dung và tông — giống như
chọn masthead (§4.5), chọn theo **bài**, không theo vòng xoay. Palette và các
điều cấm thì không đổi (đã có ở `docs/atento-image-style.md`).

| `image_style` | Dùng khi |
|---|---|
| `technical` | Bài System Design / Architecture, foundation — giải thích cấu trúc, cơ chế, trade-off. Nét vẽ kỹ thuật, đo đạc, có lưới và kết cấu. |
| `editorial` *(mặc định)* | Bài nền tảng / nghề nghiệp / mindset chung — một ý trừu tượng cần ẩn dụ tĩnh. Tĩnh vật editorial, ấm và trầm. |
| `sketch` | Essay cá nhân / ý kiến (giọng Đạt) — kể chuyện, tự vấn. Nét bút chì nhanh, hơi thô, đời thường. |
| `bulletin` | Thông báo, sự kiện, cộng đồng, tin tức — cần đọc nhanh. Bố cục poster tối giản, mảng phẳng, rõ trọng tâm. |

- Viết **đúng một** trong bốn khóa trên — không tự chế khóa mới, không dịch.
- Chọn theo **bài viết**, không chọn cho "đa dạng": một bài technical nên là
  `technical` kể cả khi bài trước cũng đã dùng `technical`.
- Pipeline có mặc định (`default_style`) nếu bạn quên, nhưng **bạn phải tự chọn**.
- Người duyệt có thể đổi lại trên `/review/{id}` trước khi sinh ảnh.

---

## 10. Checklist trước khi gửi rewrite

- [ ] Caption mở bằng **một** masthead hợp bài (§4.5) ở dòng đầu, cách hook một dòng trống.
- [ ] Đúng **một** register; xưng hô nhất quán.
- [ ] Đã chọn **format** (§5.2) hợp nhất với bài — không gò cho khác bài trước.
- [ ] Mở bài chạm trong 2 dòng đầu; luận điểm để ở cuối.
- [ ] Nội dung lấy từ bài gốc, không bịa; drama đúng liều theo register.
- [ ] Tiếng Việt tự nhiên; thuật ngữ kỹ thuật giữ tiếng Anh.
- [ ] Có trade-off hoặc góc nhìn hai chiều (bài technical).
- [ ] Đủ `#Atento` + `#fromfoundationtoexcellence` + 1 topic; hashtag nằm ở trường riêng.
- [ ] CTA đúng loại item (tuyển sinh / seminar / blog / cộng đồng).
- [ ] Nguồn ngoài: đã ghi tên **tác giả** (không kèm tên miền) và CTA dùng *"Đọc bài gốc"* (§7.3).
- [ ] Caption **không** chứa URL hay tên miền (`seangoedecke.com`) — link bài ở comment (§7.2).
- [ ] Không hype, không bịa, không engagement bait / clickbait.
- [ ] Không lặp lại opener/closer/cách dùng từ của các caption trong `recent` (§12).
- [ ] Không có tell AI: không khép bài bằng châm ngôn theo nghi thức, "không phải X mà là Y" dùng ≤1 lần, nhịp câu có so le (§12.1).
- [ ] Emoji đúng liều theo register.
- [ ] Đoạn văn: gộp các câu liên quan, ngăn câu bằng **shift-enter** trong cùng một đoạn; **dòng trống** chỉ để tách ý lớn — không mỗi câu một đoạn (§4.1, §4.4).
- [ ] `commentary` đã điền (nêu rõ format + mức drama).
- [ ] `image_prompt` đã điền: **tiếng Anh**, cụ thể, và **khác** ẩn dụ với các bài khác (cũng là alt text của ảnh).
- [ ] `image_style` đã chọn: **một** khóa hợp bài (§9.2).
- [ ] `voice` đã chọn: **một** khóa hợp bài (§3) — đã đọc file voice tương ứng.

---

## 11. Vocabulary banks

Each voice's signature phrases now live **with that voice**, so they are read
together with its samples:

- Technical (Dũng) → `docs/voices/technical.md` (§Vocabulary bank)
- Essay (Đạt) → `docs/voices/essay.md` (§Diction)
- Community (Page) → `docs/voices/announcement.md` (§Signature moves)
- Funny → `docs/voices/funny.md` (§Signature moves)

Scene openings any format can reuse stay in §5.6.

---

## 12. Đừng viết như AI — các "tell" phải tránh

Một bài đọc "như AI" không phải vì nó sai, mà vì nó **đều và sạch quá** — cùng
một nhịp câu, cùng một câu chốt, cùng một mô-típ đối lập, lặp qua nhiều bài. Chỉ
cần liếc qua là thấy một tài khoản mà bài nào cũng na ná nhau. Người đọc không
gọi tên được, nhưng cảm giác đó làm giảm độ tin.

`GET /api/drafts` trả thêm trường **`recent`** — vài caption mới viết gần nhất
(đã có masthead). **Đọc nó trước khi viết**, để không lặp lại cách mở bài / câu
chốt / từ vựng của các bài liền trước.

### 12.1 Những mô-típ dễ lộ nhất (tránh dùng như mặc định)

- **Câu chốt châm ngôn khép mọi bài.** Không phải bài nào cũng cần một câu
  *"X không nằm ở A. X là B."* Kết bằng một chi tiết cụ thể, một câu hỏi để lửng,
  hoặc dừng ngay sau luận điểm — cũng đủ. Đừng biến "câu chốt đắt" thành nghi
  thức bắt buộc cho từng bài.
- **Đối lập "không phải X, mà là Y".** Dùng **tối đa một lần** trong một bài; nếu
  đã dùng ở câu mở thì đừng lặp lại ở câu chốt.
- **Nhịp câu đều tăm tắp.** Tránh bài mà câu nào cũng dài tầm nhau. Cố ý đặt một
  câu cụt ba chữ, một câu dài nhiều mệnh đề, một câu hỏi ngắn — sự so le đó là
  thứ người viết thật luôn có.
- **Mở bài bằng công thức quen:** *"Ai cũng biết…"*, *"Ai cũng nói…"*,
  *"Bạn có bao giờ…"*, *"Hãy tưởng tượng…"*, *"Trong thế giới…"*. Nếu định dùng,
  gắn ngay một chi tiết cụ thể; tốt hơn là vào thẳng khoảnh khắc (§5.1).
- **Liệt kê danh từ trừu tượng:** *"trusted, contextual, traceable, governed and
  operational"*. Một chuỗi ba-bốn tính từ/cụm danh từ nghe rất "AI". Chọn một cái
  đáng nói nhất rồi mổ nó ra.
- **Ba vế đối xứng ("rule of three"):** *"nhanh, gọn, chính xác"*, *"đơn giản,
  nhanh, rẻ"*. Ba vế cùng hình dạng là một tell rất rõ — rút còn **hai vế**, hoặc
  chọn một vế đắt nhất rồi khai thác. Liệt kê thật theo *"Thứ nhất…, Thứ hai…"* thì
  được, miễn mỗi vế có nội dung riêng chứ không phải ba tính từ đồng nghĩa.
- **Cụm chuyển ý vô nghĩa:** *"về cơ bản"*, *"trong bối cảnh hiện nay"*, *"có thể
  nói rằng"*, *"một cách tổng quát"*. Cắt thẳng vào ý. (Vài cụm như
  *"Hãy tưởng tượng…"*, *"Điều quan trọng cần chú ý là…"* — là giọng đặc trưng
  của `technical`, không phải tell.)
- **Đối xứng hoàn hảo.** Đoạn nào cũng mở-thân-kết gọn ghẽ, không chỗ nào gồ ghề.
  Cho phép một câu dang dở, một chỗ tự sửa lại ý, một câu hỏi chưa được trả lời.
- **Hype rỗng:** "cách mạng", "đột phá", "thay đổi mọi thứ", "tốt nhất" (§8).

### 12.2 Cách sửa: cụ thể hoá, đừng chỉ đổi từ đồng nghĩa

Vấn đề gốc thường không nằm ở tính từ mà ở **thiếu chi tiết cụ thể**. Một bài có
chi tiết thật thì tự khắc khác nhau.

| Kém (chung chung, dễ lộ AI) | Tốt hơn (cụ thể) |
|---|---|
| "Kafka giúp hệ thống mở rộng tốt hơn." | "Order service ngừng gọi Inventory. Nó chỉ đẩy một event rồi đi làm việc khác." |
| "Nhiều kỹ sư thiếu foundation." | "Đọc hàng nghìn CV, phỏng vấn hàng trăm ứng viên — vẫn cùng một câu hỏi không ai trả lời được." |
| "Đổi lại đều có giá." | "Từ 32 bit xuống 8 bit gần như không thấy khác. Xuống 4 bit thì model bắt đầu quên fact." |

### 12.3 Không được tự sinh thêm tell khi sửa

Đừng "chống AI" bằng cách chèn khẩu ngữ rẻ tiền, emoji, hay câu cụt vô nghĩa.
Register và xưng hô vẫn theo §3–§4; masthead, CTA và ghi nguồn (§7) không đổi.
**Mục tiêu là một bài mà người thật đọc thấy tự nhiên** — không phải một bài trông
cố tỏ ra "người".

Pipeline chỉ **đọc và ghi nhận** các tell này (advisory) và hiện nhắc trên
`/review/{id}`; nó **không tự sửa caption**. Sửa hay không là việc của bạn và
người duyệt.
