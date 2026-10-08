# Benchmark: 20 generated plans (seeds 100-119)

Same OpenCV parser in both columns. PlanVerse adds TopologyGuard + ScaleLock.

| Metric | Baseline | PlanVerse |
|---|---|---|
| room_recall | 0.337 | 0.9631 |
| room_precision | 0.6625 | 0.9917 |
| room_iou_matched | 0.6393 | 0.9756 |
| room_iou_all | 0.2876 | 0.9404 |
| room_type_accuracy | 0.8767 | 0.9762 |
| dimension_error_pct | 15.5386 | 1.1216 |
| scale_error_pct | 3.209 | 0.6806 |
| structural_consistency | 0.9014 | 0.9912 |
| doors F1 (micro) | 0.9919 | 0.9919 |
| windows F1 (micro) | 0.9888 | 0.9888 |

Automatically calibrated: 20/20

Generated plans are drawn in one conventional style with injected wall breaks and junction gaps; results on real-world plans will differ. Baseline uses an estimated scale because it has no ScaleLock.
