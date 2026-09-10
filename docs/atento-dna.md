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
2. Pick the register (§3) that fits the item — technical essay, personal
   essay, or page announcement.
3. Choose an **opening format** from the menu (§5) and rotate — don't repeat the
   previous post's format. Write the caption in **Vietnamese** following §4–§7.
   Keep technical terms in **English** (§4.3).
4. Return JSON: `caption`, `hashtags`, `cta`, `alt_text`, `commentary` (§9).
5. Self-check against §10 before submitting.

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

## 3. Three registers — pick one

Atento có ba giọng khác nhau; trộn chúng vào một bài sẽ lệch tông. Cả ba đều mở
bằng một **format** ở §5, chỉ khác liều drama.

### 3.1 Technical / thought-leadership (giọng Dũng)
- **Người kể:** "tôi" / "chúng ta". Điềm tĩnh, chặt chẽ, không hype.
- **Cách vào:** một **sự cố/khoảnh khắc cụ thể** của hệ thống, một buổi phỏng
  vấn, một **ví von**, hoặc "câu trả lời an toàn rồi lật" (§5.2). Nếu dùng
  "Hãy tưởng tượng…" thì phải gắn ngay một tình huống.
- **Cách đi:** tình huống → vì sao giải pháp cũ hết đất → khái niệm mới →
  **trade-off** → kết luận.
- **Luôn có:** mặt trái của giải pháp. *"EDA không phải lời giải cho mọi bài toán."*
- **Chốt bài** bằng một câu đáng nhớ, thường ở dạng quote:
  - *"API là ngôn ngữ của các ứng dụng, Event là ngôn ngữ của những hệ thống có khả năng mở rộng."*
- **Ví von đặc trưng:** xây nhà/chung cư; thuê DVD vs Netflix; "mài dao thật sắc".

### 3.2 Personal essay / opinion (giọng Đạt)
- **Người kể:** "mình", gọi người đọc là "bạn" / "anh em" / "mấy ông".
- **Cách vào:** một khoảnh khắc, một **nghịch lý**, một **lời tự thú**, hoặc một
  **câu hỏi thẳng** (§5.2) — rồi mới đặt câu hỏi tu từ.
- **Cách đi:** kể chuyện → đặt câu hỏi tu từ → lật góc nhìn → rút ra bài học.
- **Khẩu ngữ được phép:** "khỉ thật", "chả đùa chứ", "mấy ông", "anh em",
  "ngon đét", "dẹp cái văn đó đi", "thú thật đi", "đúng không nào?", "thế nhé!".
- **Hài + tự trào + emoji** 😄 😂 🙇‍♂️; kết bằng "Chúc mọi người luôn vui vẻ và hạnh phúc. 🙇‍♂️".
- **Series nhận diện:** *"Biết vậy thì đã…"* (mình thử rồi, kể để mọi người khỏi thử sai).
- **Câu chốt ngắn, hay lặp lại:** *"Try. Error. Retry."*, *"See the world as it is."*
- **Cảnh báo:** đây là giọng mạnh — chỉ dùng cho bài essay/mindset, **không** dùng
  cho thông báo tuyển sinh hay bài kỹ thuật thuần.

### 3.3 Page announcement / community (giọng Facebook)
- **Người kể:** "Atento" / "chúng tôi", gọi người đọc là "các bạn" / "mấy ní".
- **Tông:** ấm, thân mật, có chút đùa: "shop", "nhoaaaa", "nha", "ạ", "hihi".
- **Cách vào:** một khoảnh khắc cộng đồng ngắn (phòng học kín người, một bạn
  online từ TP.HCM) → rồi tới thông tin chính. Drama **thấp**, không kịch.
- **Cấu trúc:** mở bằng khoảnh khắc/thông tin chính + emoji → gạch đầu dòng
  thông tin (📆 🕒 💲 🎓 📍) → CTA "Link dưới comment" → hashtag.
- **Emoji dày** 🥰 😍 🤩 🥳 ✅ ❌ ❗️ ⏳ 📩 🫶, đặt ở đầu dòng.
- **Ví dụ thật:**
  - *"❌Tại Atento, chúng tôi không dạy lập trình đơn thuần rập khuôn… ✅Tại Atento, chúng tôi truyền đạt cách tư duy…"*
  - *"Đăng ký theo nhóm hoặc giới thiệu học viên để được nhận thêm ưu đãi nhoaaaa. 😊 Link dưới comment ạ. 🫶"*
  - *"Văn hoa thế đủ rồi nhỉ 😌 Các bạn làm bài tập về nhà chưa? 😈"*
- **Recap sự kiện:** biết ơn + khiêm tốn, nhấn "học từ đồng môn", "kết nối cộng đồng".

---

## 4. Language & tone rules

### 4.1 Ngôn ngữ
- Caption **tiếng Việt** là chính. Viết tự nhiên như người Việt nói, không dịch máy.
- Câu ngắn, đoạn ngắn (1–3 câu). Ý lớn tách bằng dòng trống.
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
- Câu chốt/định nghĩa có thể để dạng quote (xuống dòng, nổi bật).

---

## 5. Hooks & formats — luân phiên, đừng "một màu"

Một tài khoản chỉ có **một kiểu mở bài** sẽ rất đơn điệu. Có nhiều cách để câu
được người đọc; chọn theo **bản chất của bài**, và **luân phiên** giữa các bài.

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

### 5.2 Menu format mở bài (chọn theo bài, luân phiên)

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

### 5.3 Luật luân phiên (tránh "một màu")
- **Không** dùng cùng một format cho hai bài liền nhau.
- Trong một batch nhiều bài: **mỗi bài một format**; mặc định **tối đa ~1/3** là scene.
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
dung. Ghép một format (§5.2) với một template — và luân phiên format.

### 6.1 Blog promo (từ item `atento-blog`) — 80–150 từ
1. **Mở bài** — một format ở §5.2, chạm trong 2 dòng đầu (đừng lặp format bài trước).
2. **Sting + turn** — nỗi đau của dev + góc nhìn của bài. (2–3 câu)
3. **Payoff / teaser** — câu chốt đáng nhớ, không spoil hết.
4. **CTA + link** — "Đọc đầy đủ tại: <link bài>" ở cuối caption (caption mới là
   phần được đăng).
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
`cta` là metadata cho người duyệt, **không được đăng**. Với bài blog, đặt **link
đầy đủ ở cuối caption** (bài đăng dạng ảnh, pipeline không tự đăng comment), rồi
nhắc lại câu đó trong `cta`.
- Tuyển sinh: *"Đăng ký theo nhóm hoặc giới thiệu học viên để nhận ưu đãi nhoaaaa. 😊"*
- Seminar: *"Ai còn quên chưa đăng ký thì nhanh tay để shop gửi email confirm lun nào. 📩"*
- Cộng đồng (nhẹ, gây tương tác lành mạnh): *"Các bạn làm bài tập về nhà chưa? 😈"*
- Blog: *"Đọc đầy đủ tại: <link bài>"* ở cuối caption.
- Tránh CTA kiểu engagement bait ("tag 3 người bạn", "share để nhận quà") — vi
  phạm chính sách Facebook và trái DNA.

---

## 8. Do / Don't

**Do**
- Chọn một **format mở bài** hợp với bài và **luân phiên** giữa các post (§5.2–5.3).
- Mở bằng tình huống/nghịch lý/câu hỏi chạm trong 2 dòng đầu; luận điểm để ở cuối.
- Nêu trade-off; nói cả mặt được và mặt mất.
- Kết bằng một câu chốt đáng nhớ.
- Viết hoa/viết đúng tên khóa học, thời gian, học phí, địa điểm nếu có.
- Giữ đúng vai: caption là **bản nháp cho người duyệt**, không phải bản cuối bắt buộc.

**Don't**
- ❌ Bài nào cũng mở cùng một kiểu — "một màu".
- ❌ Hype rỗng: "cách mạng", "thay đổi mọi thứ", "tốt nhất Việt Nam".
- ❌ Drama giả/clickbait: bịa tình huống, giật tít rỗng, thổi phồng hậu quả.
- ❌ Engagement bait, spam, hứa hẹn lương/thu nhập cụ thể.
- ❌ Bịa số liệu, giảng viên, đối tác, thành tích.
- ❌ Trộn ba register vào một bài.
- ❌ Việt hóa thuật ngữ kỹ thuật; hoặc nhồi tiếng Anh không cần thiết.
- ❌ Emoji tràn lan trong bài technical; emoji trong câu quote chốt.
- ❌ Dịch máy, câu dài, đoạn dày đặc.
- ❌ Nhét hashtag vào giữa caption (để ở trường `hashtags`).

---

## 9. Rewrite output contract

`POST /api/drafts/{id}/rewrite` nhận JSON:

| Field | Kiểu | Ghi chú |
|---|---|---|
| `caption` | string | Nội dung chính, tiếng Việt, **không** chứa hashtag. Mở bằng một format (§5); CTA và link bài (nếu có) nằm ở cuối — đây là phần duy nhất được đăng. |
| `hashtags` | array[string] | 2–4 tag, **kèm dấu `#`**, gồm `#Atento` + `#fromfoundationtoexcellence` + 1 topic. |
| `cta` | string | Câu kêu gọi hành động — **chỉ để người duyệt đọc**, không được đăng; bản tương ứng phải có trong `caption`. |
| `alt_text` | string | Mô tả ảnh bằng tiếng Việt, ngắn, phục vụ trợ năng. |
| `commentary` | string | 2–4 câu cho người duyệt: register nào, **format/hook** là gì, mức drama, có gì cần xác nhận. |

Ví dụ:

```json
{
  "caption": "Buổi phỏng vấn System Design. Ứng viên vẽ vanh vách Load Balancer, cache, cluster database.\n\nRồi interviewer hỏi một câu: \"Chi phí để chạy hệ thống này là bao nhiêu?\". Im lặng.\n\nThiết kế cho 1 triệu users không khó ở phần vẽ. Cái khó là những quyết định về architecture và trade-off phía sau — thứ quyết định hệ thống sống được hay không.\n\nĐó mới là lúc chúng ta thực sự phải \"design\".",
  "hashtags": ["#Atento", "#fromfoundationtoexcellence", "#systemdesign"],
  "cta": "Link khoá học System Design ở dưới comment nha. 🥰",
  "alt_text": "Giảng viên Atento trình bày về thiết kế hệ thống cho một triệu người dùng.",
  "commentary": "Register technical (giọng Dũng), format D (đám đông rồi lật), drama vừa. Luận điểm để ở cuối. Cần xác nhận link đăng ký trước khi duyệt."
}
```

---

## 10. Checklist trước khi gửi rewrite

- [ ] Đúng **một** register; xưng hô nhất quán.
- [ ] Đã chọn một **format** (§5.2) hợp bài và **khác** format bài trước — không "một màu".
- [ ] Mở bài chạm trong 2 dòng đầu; luận điểm để ở cuối.
- [ ] Nội dung lấy từ bài gốc, không bịa; drama đúng liều theo register.
- [ ] Tiếng Việt tự nhiên; thuật ngữ kỹ thuật giữ tiếng Anh.
- [ ] Có trade-off hoặc góc nhìn hai chiều (bài technical).
- [ ] Đủ `#Atento` + `#fromfoundationtoexcellence` + 1 topic; hashtag nằm ở trường riêng.
- [ ] CTA đúng loại item (tuyển sinh / seminar / blog / cộng đồng).
- [ ] Không hype, không bịa, không engagement bait / clickbait.
- [ ] Emoji đúng liều theo register.
- [ ] `alt_text` và `commentary` đã điền (commentary nêu rõ format + mức drama).

---

## 11. Vocabulary bank (signature phrases)

**Technical (Dũng):** từ gốc rễ; vững tiến đi xa; trade-off; engineering
principles; under the hood; business event; "API là ngôn ngữ của ứng dụng,
Event là ngôn ngữ của hệ thống mở rộng"; mài dao thật sắc; đối chất đến tận
cùng; "Hãy tưởng tượng…"; "Điều quan trọng cần chú ý là…".

**Essay (Đạt):** "Biết vậy thì đã…"; khỉ thật; chả đùa chứ; mấy ông; anh em;
ngon đét; dẹp cái văn đó đi; thú thật đi; đúng không nào?; "Thế nhé!"; Try.
Error. Retry.; See the world as it is.; "Chúc mọi người luôn vui vẻ và hạnh
phúc. 🙇‍♂️".

**Community (Page):** mấy ní; shop; nhoaaaa; nha; ạ; hihi; "Link dưới comment
nha. 🥰"; "Ai còn quên chưa đăng ký thì nhanh tay… 📩".

**Scene openings (dùng lại được):** "2 giờ sáng."; "Cuộc họp vừa bắt đầu.";
"Buổi phỏng vấn."; "Đơn hàng đã thanh toán xong."; "30 phút sau…"; "Im lặng.".
