# NimbusAI — GPU Cost Optimization Report

**Period:** monthly  
**Baseline spend:** $27,133  
**Optimized spend:** $14,617  
**Projected savings:** $12,516  (**46%**)

## Savings by lever

| Lever | Savings (USD) |
|---|---|
| Inference (cascade/batch/cache/reasoning) | $1,221 |
| Purchasing (spot/reserved) | $10,040 |
| Right-size util-lies | $655 |
| Kill idle GPUs | $600 |

## Sustainability

- Energy per query: 0.24 Wh
- Carbon per query: 0.091 gCO2e
- Cheapest+cleanest region: europe-north1

## Phân tích

**GPU-Util "lie".** `gpu-h100-4` báo 98.2% GPU-Util nhưng MFU chỉ 0.194. `nvidia-smi` chỉ đo % thời gian có ít nhất một kernel đang chạy, không đo SM/Tensor Core có làm việc hay không. Memory stall, batch nhỏ, kernel launch overhead hoặc data-loader chậm vẫn giữ GPU "bận" mà gần như không ra FLOPs. Hệ quả: trả $2.50/giờ nhưng chi phí thực trên mỗi giờ tính toán hữu ích là $12.89 (~5×). Hạ tier các GPU bị "lie" tiết kiệm $655/tháng.

**Bền vững.** Sau reasoning budget, inference dùng 10.4 kWh/ngày. us-east-1: $1.25 / 4.0 kg CO2e · europe-north1: $0.94 / 0.3 kg CO2e · us-east-wa: $0.57 / 0.9 kg CO2e. europe-north1 sạch nhất (−92% carbon so với us-east-1) và rẻ hơn 25% tiền điện; us-east-wa rẻ nhất về $. Chọn vùng giảm cả $ và carbon cùng lúc, nhưng phải cân nhắc latency tới người dùng — phù hợp nhất cho job batch/training có thể gián đoạn.

## Khuyến nghị (theo thứ tự ROI)

1. **Purchasing — $10,040/tháng.** Không đổi code, chỉ đổi cách mua: spot + checkpoint cho training, reserved cho inference chạy 24/7 (vượt ngưỡng hòa vốn 55% duty).
2. **Tắt GPU idle + hạ tier GPU bị "lie" — $1,255/tháng.** Đo MFU thay vì GPU-Util trước khi mua thêm GPU.
3. **Inference — $1,221/tháng.** Cascade routing là bước lớn nhất ($/1M-token −77%), sau đó batch API cho job không cần real-time.
4. **Reasoning budget + cache gate.** $ nhỏ nhưng cắt phần lớn năng lượng; áp dụng sau khi gắn tag đủ để chargeback cho team eval.

## Unit economics inference ($/1M-token, cộng dồn từng lever)

| Lever | $/ngày | $/1M-token |
|---|---|---|
| Baseline: all on large, no cache/batch | $48.87 | $6.488 |
| + Cascade (route_tier) | $11.48 | $1.523 |
| + Batch API | $9.66 | $1.282 |
| + Prompt cache (gated by break-even) | $8.90 | $1.181 |
| + Reasoning budget (keep 25%) | $8.16 | $1.083 |

## Your Turn #3 — Prompt cache có đáng không?

Ghi cache = 1.25× giá input, đọc = 0.1× → hòa vốn khi mỗi lần ghi được đọc lại **≥ 0.28 lần** ((1.25−1)/(1−0.1)). Giá model triệt tiêu nên ngưỡng giống nhau cho tier small và large; tier large chỉ tiết kiệm nhiều $ hơn mỗi lần đọc. Số lần đọc/ghi suy ra từ hit rate: N = hit / (1 − hit).

| Project | Hit rate | Đọc/ghi | Cache |
|---|---|---|---|
| (untagged) | 30.3% | 0.44 | BẬT |
| chat | 50.5% | 1.02 | BẬT |
| doc-qa | 51.1% | 1.05 | BẬT |
| nightly-eval | 7.2% | 0.08 | TẮT |
| web-search | 7.2% | 0.08 | TẮT |

Cache mọi nơi: $9.11/ngày; chỉ cache project vượt ngưỡng: $8.90/ngày → tiết kiệm **$0.21/ngày**. nightly-eval và web-search gần như không đọc lại prefix nên cache chỉ làm tăng phí ghi.

## Your Turn #4 — Ngân sách Reasoning

Reasoning chiếm **8.4% traffic** nhưng **15.9% chi phí inference** và **94.0% năng lượng** ($1.41/ngày, 29,788 Wh/ngày). Tốn ~80× năng lượng vì model sinh chuỗi suy luận dài (~6× output token ở đây) trước khi trả lời; decode là pha memory-bound, mỗi token đều đọc lại toàn bộ trọng số + KV-cache, nên Wh tăng theo độ dài chuỗi.

**Quy tắc routing:** chỉ bật reasoning cho 25% request reasoning có prompt dài nhất (proxy độ phức tạp); phần còn lại trả lời như request thường (tối đa 641 token output). Kết quả: tiết kiệm $0.74/ngày và 21,230 Wh/ngày (−67% năng lượng inference).

| Giữ reasoning | % traffic | $/ngày | $ tiết kiệm | Wh/ngày | Wh tiết kiệm |
|---|---|---|---|---|---|
| 100% | 8.4% | $8.90 | $0.00 | 31,675 | 0 |
| 50% | 4.2% | $8.43 | $0.46 | 18,941 | 12,734 |
| 25% | 2.1% | $8.16 | $0.74 | 10,446 | 21,230 |
| 10% | 0.8% | $7.94 | $0.96 | 5,390 | 26,285 |
| 0% | 0.0% | $7.87 | $1.03 | 2,065 | 29,610 |

_Figures are June-2026 as-of snapshots; re-baseline before acting._