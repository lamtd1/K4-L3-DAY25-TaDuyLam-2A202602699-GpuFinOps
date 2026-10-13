# Lab 25 — Bài viết ngắn: Tối ưu chi phí GPU cho NimbusAI

_Số liệu lấy từ `python missions/run_all.py` (seed = 25). Chi tiết đầy đủ trong `outputs/report.md`._

## 1. Baseline vs. Optimized

| | Baseline | Optimized | Thay đổi |
|---|---|---|---|
| Tổng chi phí / tháng | $27,133 | $14,617 | **−46.1%** |
| Inference $/1M-token | $6.488 | $1.083 | **−83.3%** |

## 2. Đòn bẩy nào đóng góp nhiều nhất?

| Lever | Tiết kiệm / tháng | Tỷ trọng |
|---|---|---|
| Purchasing (spot/reserved) | $10,040 | 80% |
| Inference (cascade/batch/cache/reasoning) | $1,221 | 10% |
| Right-size GPU bị "lie" | $655 | 5% |
| Tắt GPU idle | $600 | 5% |

**Purchasing thắng áp đảo** vì đội GPU tự vận hành ($25,667/tháng on-demand) lớn gấp ~17 lần hóa đơn inference API. Training có thể checkpoint nên chạy spot rẻ hơn ~37% (job-train-llm: $12,000 → $7,596). Inference chạy 24/7 vượt ngưỡng hòa vốn 55% nên mua reserved.
Trong inference, **cascade** là bước lớn nhất: $/1M-token giảm từ $6.49 xuống $1.52 (−77%), vì 79% request chỉ cần model small.

## 3. GPU-Util Lie

- `gpu-h100-4`: GPU-Util 98.2% nhưng MFU 0.194. `gpu-a10g-1`: 96.9% nhưng MFU 0.268.
- `nvidia-smi` chỉ đo % thời gian có kernel chạy, không đo Tensor Core có làm việc hay không. Memory stall, batch nhỏ và launch overhead vẫn hiện là "bận".
- **Tác động tài chính:** trả $2.50/giờ cho H100 nhưng chỉ nhận ~1/5 FLOPs, nên chi phí thực là **$12.89 cho mỗi giờ tính toán hữu ích** (~5×). Hạ tier (H100→A100, A10G→L4) tiết kiệm **$655/tháng**.

## 4. Phần mở rộng đã làm

**#3 — `cache_is_worth_it()`** (`finops/pricing.py`, áp dụng trong M2)
- Ghi cache tốn 1.25×, đọc tốn 0.1× giá input, nên hòa vốn khi mỗi lần ghi được đọc lại **≥ 0.28 lần**. Ngưỡng không phụ thuộc giá model, nên giống nhau cho tier small và large.
- Số lần đọc/ghi thực tế (N = hit/(1−hit)): chat 1.02, doc-qa 1.05 → **BẬT** cache. nightly-eval và web-search chỉ 0.08 → **TẮT** cache.
- Chỉ cache project vượt ngưỡng rẻ hơn cache mọi nơi **$0.21/ngày**. **Insight:** cache không phải lúc nào cũng có lợi; prefix không được đọc lại thì chỉ tốn thêm phí ghi.

**#4 — Ngân sách Reasoning** (`missions/m2_inference_levers.py`)
- Reasoning chiếm **8.4% traffic nhưng 15.9% chi phí và 94% năng lượng** inference.
- Năng lượng gấp ~80× vì model sinh chuỗi suy luận dài (~6× output token). Decode là pha memory-bound, mỗi token phải đọc lại toàn bộ trọng số và KV-cache.
- **Quy tắc routing:** chỉ bật reasoning cho 25% request reasoning có prompt dài nhất; phần còn lại trả lời như request thường. Kết quả: −$0.74/ngày, **−21,230 Wh/ngày (−67%)**. Nếu giữ 10% thì −$0.96/ngày và −26,285 Wh/ngày.
- **Insight:** về $ đây là lever nhỏ, nhưng là lever năng lượng/carbon lớn nhất.

## 5. Ba hành động đầu tiên nếu tôi là FinOps lead

1. **Đổi cách mua GPU** (−$10k/tháng, không cần sửa code): spot + checkpoint cho training, reserved cho inference 24/7.
2. **Đưa MFU lên dashboard thay cho GPU-Util**, rồi tắt GPU idle và hạ tier GPU bị "lie" (−$1.3k/tháng).
3. **Bật cascade routing + Batch API** cho inference, và đặt reasoning budget cho team eval (−$1.2k/tháng, −67% năng lượng inference). Chuyển job batch sang europe-north1 để giảm 92% carbon.
