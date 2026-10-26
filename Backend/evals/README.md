# 确定性约束评测

运行：在项目根目录执行 `.venv/bin/python Backend/scripts/evaluate.py`。
报告：`docs/offline-evaluation.json`。失败退出码为 1，可用于本地验收。

当前 33 项分三组：

- `specific`：17 项原具体食宿模式，保留城市、日期、引用、预算、时间、距离等回归。
- `browse`：8 项默认按需食宿，检查自由用餐、同日位置参照、住宿区域和预算留白。
- `availability`：8 项抵离空日，检查超出可用时间、用户休息日、日期完整性、必去及住宿预算不能豁免。

`cases.json` 每项指定基线文件和 `[路径, 值]` 修改项，`passed` 是预期发布结论。`codes` 检查任意严重级别，`error_codes`、`warning_codes` 分别检查严重级别，避免把警告误当阻断。报告逐项列出实际错误和警告。

旧 `far_hotel` 曾要求拒绝所有远距离酒店，与已发布的“保留用户住宿并显示长通勤风险”规则不符，现预期通过并必须包含 `distant_hotel` 警告；活动间时间不足的 `cross_district_meal` 仍必须拒绝。

这些是合成夹具的约束检测，不调用模型和地图，不代表自然语言规划成功率、实地可行性或性能分布。真实样本另记于 `docs/reviews/availability-live-2026-10-25.json`。领域边界、暂停恢复和正式版保护仍由 `Backend/tests` 回归验证。
