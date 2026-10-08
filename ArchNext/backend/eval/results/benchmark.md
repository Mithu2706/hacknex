# Synthetic benchmark — 20 generated floor plans. Results do not establish real-world accuracy.

Seeds 100-119. OpenCV structural parser (identical in all configurations).

| Metric | Baseline | TopologyGuard only | ScaleLock only | Full ArchNext |
|---|---|---|---|---|
| room_recall | 0.337 | 0.9631 | 0.337 | 0.9631 |
| room_precision | 0.6625 | 0.9917 | 0.6625 | 0.9917 |
| room_iou_matched | 0.6393 | 0.9756 | 0.6393 | 0.9756 |
| room_iou_all | 0.2876 | 0.9404 | 0.2876 | 0.9404 |
| room_type_accuracy | 0.8767 | 0.9762 | 0.8767 | 0.9762 |
| dimension_error_pct | 15.5386 | 4.6753 | 13.7304 | 1.1216 |
| scale_error_pct | 3.209 | 3.3148 | 1.4241 | 0.6806 |
| structural_consistency | 0.9014 | 0.9912 | 0.9014 | 0.9912 |
| doors F1 (micro) | 0.9919 | 0.9919 | 0.9919 | 0.9919 |
| windows F1 (micro) | 0.9888 | 0.9888 | 0.9888 | 0.9888 |

Reproducibility check: identical on re-run

Configurations without ScaleLock use the estimated scale (typical door width), so their scale and dimension errors measure that fallback.
